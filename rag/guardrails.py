"""Layered input policies, evidence integrity and conservative claim verification."""

import re
import threading
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import numpy as np

from .config import Settings
from .schemas import Citation, ConflictAssessment, Document, Generation, Hit, Query

INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions|"
    r"reveal\s+(?:the\s+)?system\s+prompt|<\|(?:system|im_start)\|>|"
    r"\[INST\]|<script\b|javascript:",
    re.I,
)
SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
UNSAFE = re.compile(
    r"(?:steal|exfiltrate|dump)\s+(?:all\s+)?(?:passwords|credentials|secrets)", re.I
)
HIGH_RISK = re.compile(
    r"\b(?:medical|diagnosis|lawsuit|legal advice|investment|terminate employee)\b", re.I
)


class RejectedInput(ValueError):
    """Input violates the configured enterprise content policy."""


def suspicious(text: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    return bool(
        INJECTION.search(normalized) or SECRET.search(normalized) or UNSAFE.search(normalized)
    )


def validate_query(query: Query) -> Query:
    text = unicodedata.normalize("NFKC", query.text)
    if any(unicodedata.category(c) in {"Cc", "Cf"} and c not in "\n\t" for c in text):
        raise RejectedInput("Control characters are not allowed")
    if suspicious(text):
        raise RejectedInput("Query violates the input policy")
    return Query(text=" ".join(text.split()))


def validate_document(document: Document) -> None:
    # Preserve document text verbatim: normalizing it would invalidate source offsets.
    if suspicious(document.text) or suspicious(document.title) or suspicious(document.source):
        raise RejectedInput("Document requires security review before ingestion")
    if not document.source.startswith(("https://", "urn:")):
        raise RejectedInput("Sources must be HTTPS URLs or URNs")
    if any(unicodedata.category(c) in {"Cc", "Cf"} and c not in "\n\t\r" for c in document.text):
        raise RejectedInput("Document contains unsafe control characters")


class Entailment(Protocol):
    def scores(self, pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float]]:
        """Return (entailment, contradiction) scores for (premise, hypothesis)."""
        ...


class DemoEntailment:
    """Only exact extracts pass offline; this is not a semantic hallucination detector."""

    def scores(self, pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float]]:
        return [(1.0 if claim in context else 0.0, 0.0) for context, claim in pairs]


class NeuralEntailment:
    """NLI model independent of the generator; refuses silently truncated judgments."""

    def __init__(self, settings: Settings) -> None:
        import torch
        from sentence_transformers import CrossEncoder

        self.settings = settings
        self.model = CrossEncoder(
            settings.nli_model,
            revision=settings.nli_revision,
            max_length=512,
            device=settings.inference_device,
            activation_fn=torch.nn.Identity(),
            local_files_only=settings.local_models_only,
            trust_remote_code=False,
        )
        labels = self.model.model.config.num_labels
        if max(settings.nli_entailment_index, settings.nli_contradiction_index) >= labels:
            raise ValueError("NLI label mapping is invalid")
        self.lock = threading.Lock()

    def scores(self, pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float]]:
        if not pairs:
            return []
        with self.lock:
            for context, claim in pairs:
                if len(self.model.tokenizer(context, claim, truncation=False)["input_ids"]) > 512:
                    raise ValueError("NLI input too long for reliable verification")
            logits = np.asarray(self.model.predict(list(pairs), show_progress_bar=False))
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        if not np.isfinite(probabilities).all():
            raise ValueError("Non-finite NLI scores")
        return [
            (
                float(row[self.settings.nli_entailment_index]),
                float(row[self.settings.nli_contradiction_index]),
            )
            for row in probabilities
        ]


@dataclass
class GuardResult:
    accepted: bool
    faithfulness: float | None
    reasons: list[str]
    citations: list[Citation]
    conflicts: list[tuple[int, str]] = field(default_factory=list)


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """Resolve a quote to exact source offsets, tolerating only whitespace changes.

    PDF line wrapping is often normalized by generators. Match the same words,
    case and punctuation in a contiguous span, then return the original slice.
    This is not fuzzy matching: omitted or changed words must still fail.
    """
    if not quote.strip():
        return None
    start = text.find(quote)
    if start >= 0:
        return start, start + len(quote)
    pattern = r"\s+".join(re.escape(part) for part in quote.split())
    match = re.search(pattern, text)
    return match.span() if match else None


class HallucinationGuard:
    """Every claim needs authentic evidence plus entailment; conflicts fail closed."""

    def __init__(self, settings: Settings, nli: Entailment) -> None:
        self.settings, self.nli = settings, nli

    def check(self, output: Generation, contexts: list[Hit]) -> GuardResult:
        if output.abstain:
            return GuardResult(False, None, ["model_abstained"], [])
        if not output.claims:
            return GuardResult(False, None, ["empty_answer"], [])
        by_id = {hit.chunk.id: hit.chunk for hit in contexts}
        citations: list[Citation] = []
        checks: list[tuple[str, str]] = []
        for index, claim in enumerate(output.claims):
            if suspicious(claim.text):
                return GuardResult(False, 0.0, ["unsafe_output"], [])
            quotes: list[str] = []
            for evidence in claim.evidence:
                chunk = by_id.get(evidence.chunk_id)
                span = locate_quote(chunk.text, evidence.quote) if chunk else None
                if not chunk or span is None or suspicious(evidence.quote):
                    return GuardResult(False, 0.0, ["invalid_citation"], [])
                local_start, local_end = span
                source_quote = chunk.text[local_start:local_end]
                quotes.append(source_quote)
                citations.append(
                    Citation(
                        number=len(citations) + 1,
                        claim_index=index,
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        version=chunk.version,
                        source=chunk.source,
                        title=chunk.title,
                        quote=source_quote,
                        start=chunk.start + local_start,
                        end=chunk.start + local_end,
                    )
                )
            checks.append(("\n".join(quotes), claim.text))
        # Also examine every retrieved passage for contradictions, including uncited ones.
        context_checks = [
            (hit.chunk.text, claim.text) for claim in output.claims for hit in contexts
        ]
        scores = self.nli.scores(checks + context_checks)
        if len(scores) != len(checks) + len(context_checks):
            raise ValueError("Incomplete NLI output")
        supported = [
            score[0] >= self.settings.entailment_threshold
            and score[1] <= self.settings.contradiction_threshold
            for score in scores[: len(checks)]
        ]
        # An NLI score is a suspicion, not proof of incompatible source facts.
        # Keep the exact pairs so live orchestration can distinguish an omission
        # in an unrelated excerpt from a genuine contradictory assertion.
        conflicts = [
            (index, hit.chunk.id)
            for (index, hit), score in zip(
                [(i, hit) for i in range(len(output.claims)) for hit in contexts],
                scores[len(checks) :],
                strict=True,
            )
            if score[1] > self.settings.contradiction_threshold
        ]
        reasons = ([] if all(supported) else ["unsupported_claim"]) + (
            ["conflicting_context"] if conflicts else []
        )
        return GuardResult(
            not reasons, sum(supported) / len(supported), reasons, citations, conflicts
        )


def resolve_conflicts(
    result: GuardResult, assessment: ConflictAssessment, contexts: list[Hit]
) -> GuardResult:
    """Clear only fully adjudicated conflict suspicions; other failures stay closed.

    The model must address every pair exactly once. A claimed contradiction must
    identify an authentic counter-quote. Uncertain/invalid assessments never release.
    The caller still applies high-risk and degraded-retrieval review policies.
    """
    if result.reasons != ["conflicting_context"] or not result.conflicts:
        return result
    ids = [v.pair_id for v in assessment.verdicts]
    if len(ids) != len(result.conflicts) or set(ids) != set(range(len(result.conflicts))):
        raise ValueError("Conflict assessment did not cover every pair exactly once")
    by_id = {hit.chunk.id: hit.chunk for hit in contexts}
    for verdict in assessment.verdicts:
        if verdict.relation == "contradiction":
            chunk = by_id[result.conflicts[verdict.pair_id][1]]
            if not verdict.counter_quote or locate_quote(chunk.text, verdict.counter_quote) is None:
                raise ValueError("Contradiction lacks an authentic counter-quote")
        elif verdict.counter_quote is not None:
            raise ValueError("Non-contradiction verdict must not invent counter-evidence")
    if any(v.relation != "compatible" for v in assessment.verdicts):
        return result
    return replace(result, accepted=True, reasons=[], conflicts=[])


def render_answer(output: Generation, citations: list[Citation]) -> str:
    """Deterministic plain-text formatting; frontends must escape text when rendering HTML."""
    lines = []
    for index, claim in enumerate(output.claims):
        references = " ".join(
            f"[{citation.number}]" for citation in citations if citation.claim_index == index
        )
        lines.append(f"{claim.text.strip()} {references}")
    return "\n\n".join(lines)
