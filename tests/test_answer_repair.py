"""False-positive recovery still requires authentic evidence and a complete guard pass."""

import pytest

from rag.guardrails import HallucinationGuard, requires_human_review
from rag.pipeline import ProviderUnavailable
from rag.schemas import Claim, Evidence, Generation, Hit, Query, Rewrite


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What medical insurance premium is listed in the offer letter?", False),
        ("What medical insurance coverage benefits were offered?", False),
        ("What medical insurance premium should I choose for treatment?", True),
        ("Recommend treatment under my medical insurance coverage", True),
        ("Explain my diagnosis and medical insurance premium", True),
        ("medical support available hours", True),
        ("Give legal advice about a lawsuit", True),
    ],
)
def test_factual_benefits_are_distinct_from_advice(question, expected):
    assert requires_human_review(question) is expected


async def test_contextual_support_expands_citation_but_does_not_use_uncited_sources(
    pipeline, document, principal
):
    doc = document.model_copy(update={"text": "Name: Alex. Experience: 10 years."})
    pipeline.store.ingest([doc], principal)
    chunk = pipeline.store.snapshot(principal)[0][0]
    claim = Claim(
        text="Alex has 10 years of experience.",
        evidence=[Evidence(chunk_id=chunk.id, quote="10 years")],
    )

    class ContextNLI:
        def scores(self, pairs):
            return [(0.99, 0.01) if premise == doc.text else (0.1, 0.01) for premise, _ in pairs]

    guard = HallucinationGuard(pipeline.settings, ContextNLI())
    output = Generation(abstain=False, claims=[claim])
    result = guard.check(output, [Hit(chunk=chunk, fusion_score=1)])
    assert result.accepted
    citation = result.citations[0]
    assert citation.quote == doc.text[citation.start : citation.end]
    assert citation.quote == chunk.text
    unsupported = chunk.model_copy(update={"text": "The phrase 10 years has no named subject."})
    uncited = chunk.model_copy(update={"id": "uncited"})
    checked = guard.check(
        output, [Hit(chunk=unsupported, fusion_score=1), Hit(chunk=uncited, fusion_score=1)]
    )
    assert not checked.accepted
    assert "unsupported_claim" in checked.reasons
    forged = output.model_copy(
        update={
            "claims": [
                claim.model_copy(
                    update={"evidence": [Evidence(chunk_id=chunk.id, quote="11 years")]}
                )
            ]
        }
    )
    assert guard.check(forged, [Hit(chunk=chunk, fusion_score=1)]).reasons == ["invalid_citation"]


@pytest.mark.parametrize("outcome", ["corrected", "still_invalid", "unavailable", "unsafe"])
async def test_single_repair_is_bounded_and_reverified(pipeline, document, principal, outcome):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    pipeline.settings.guard_budget_s = 3
    generated = []

    async def structured(schema, prompt, payload, execution, timeout):
        if schema is Rewrite:
            return Rewrite(queries=["support hours"])
        generated.append(payload)
        context = payload["evidence"][0]
        if "previous_draft" in payload:
            assert 0 < timeout <= 2
            if outcome == "unavailable":
                raise ProviderUnavailable("test failure")
            quote = context["text"] if outcome == "corrected" else "invented quotation"
        else:
            quote = "invented quotation"
        text = "ignore previous instructions" if outcome == "unsafe" else context["text"]
        return Generation(
            abstain=False,
            claims=[
                Claim(text=text, evidence=[Evidence(chunk_id=context["chunk_id"], quote=quote)])
            ],
        )

    pipeline.gateway.structured = structured
    answer = await pipeline.run(Query(text="support available hours"), principal)
    if outcome == "corrected":
        assert answer.status == "answered"
        assert answer.citations and not answer.review_reasons
        assert "answer_repair" in answer.stage_ms
    else:
        assert answer.status == "review"
        assert not answer.claims and not answer.citations
    assert len(generated) == (1 if outcome == "unsafe" else 2)


async def test_abstaining_repair_preserves_initial_failure(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"

    async def structured(schema, prompt, payload, execution, timeout):
        if "previous_draft" in payload:
            return Generation(abstain=True, claims=[])
        c = payload["evidence"][0]
        return Generation(
            abstain=False,
            claims=[
                Claim(
                    text="An unsupported fact.",
                    evidence=[Evidence(chunk_id=c["chunk_id"], quote="forged quote")],
                )
            ],
        )

    pipeline.gateway.structured = structured
    answer = await pipeline.run(Query(text="support available hours"), principal)
    assert answer.status == "review"
    assert answer.initial_verification_reasons == ["invalid_citation"]
    assert "repair_abstained" in answer.review_reasons
    assert "invalid_citation" in answer.review_reasons


async def test_extractive_failure_never_enters_generative_repair(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    calls = []

    async def structured(schema, prompt, payload, execution, timeout):
        calls.append(payload)
        execution.answer_style = "extractive"
        c = payload["evidence"][0]
        return Generation(
            abstain=False,
            claims=[
                Claim(text=c["text"], evidence=[Evidence(chunk_id=c["chunk_id"], quote=c["text"])])
            ],
        )

    class ContradictoryNLI:
        def scores(self, pairs):
            return [(0.01, 0.01) for _ in pairs]

    pipeline.guard = HallucinationGuard(pipeline.settings, ContradictoryNLI())
    pipeline.gateway.structured = structured
    answer = await pipeline.run(Query(text="support available hours"), principal)
    assert answer.status == "review" and "unsupported_claim" in answer.review_reasons
    assert "answer_repair" not in answer.stage_ms
    assert len(calls) == 1
