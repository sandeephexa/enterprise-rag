"""Omissions can coexist with supported facts; real conflicts still require review."""

import pytest

from rag.guardrails import GuardResult, resolve_conflicts
from rag.pipeline import ProviderUnavailable
from rag.schemas import (
    Claim,
    ConflictAssessment,
    ConflictVerdict,
    Evidence,
    Generation,
    Hit,
    Query,
    Rewrite,
)


def assessment(relation="compatible", quote=None, ids=(0,)):
    return ConflictAssessment(
        verdicts=[
            ConflictVerdict(
                pair_id=i,
                relation=relation,
                counter_quote=quote,
                reason="Assess assertions within the same entity and scope.",
            )
            for i in ids
        ]
    )


async def test_omission_can_clear_only_conflict_reason(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    chunk = pipeline.store.snapshot(principal)[0][0]
    result = GuardResult(False, 1.0, ["conflicting_context"], [], [(0, chunk.id)])
    resolved = resolve_conflicts(result, assessment(), [Hit(chunk=chunk, fusion_score=1)])
    assert resolved.accepted
    assert resolved.reasons == []
    assert not result.accepted  # Original result is not mutated.
    unsupported = GuardResult(
        False, 0.0, ["unsupported_claim", "conflicting_context"], [], [(0, chunk.id)]
    )
    assert resolve_conflicts(unsupported, assessment(), []) is unsupported


@pytest.mark.parametrize("relation", ["contradiction", "uncertain"])
async def test_real_or_uncertain_conflict_is_not_released(pipeline, document, principal, relation):
    pipeline.store.ingest([document], principal)
    chunk = pipeline.store.snapshot(principal)[0][0]
    result = GuardResult(False, 1.0, ["conflicting_context"], [], [(0, chunk.id)])
    verdict = assessment(relation, chunk.text if relation == "contradiction" else None)
    assert not resolve_conflicts(result, verdict, [Hit(chunk=chunk, fusion_score=1)]).accepted


@pytest.mark.parametrize("ids", [(1,), (0, 0)])
async def test_bad_pair_coverage_fails_closed(pipeline, document, principal, ids):
    pipeline.store.ingest([document], principal)
    chunk = pipeline.store.snapshot(principal)[0][0]
    result = GuardResult(False, 1.0, ["conflicting_context"], [], [(0, chunk.id)])
    with pytest.raises(ValueError, match="every pair"):
        resolve_conflicts(result, assessment(ids=ids), [Hit(chunk=chunk, fusion_score=1)])


async def test_fabricated_counter_quote_rejected(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    chunk = pipeline.store.snapshot(principal)[0][0]
    result = GuardResult(False, 1.0, ["conflicting_context"], [], [(0, chunk.id)])
    with pytest.raises(ValueError, match="counter-quote"):
        resolve_conflicts(
            result,
            assessment("contradiction", "An invented prohibition."),
            [Hit(chunk=chunk, fusion_score=1)],
        )


@pytest.mark.parametrize("outcome", ["compatible", "contradiction", "uncertain", "unavailable"])
async def test_live_conflict_adjudication_policy(pipeline, document, principal, outcome):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    calls = []

    class SuspectNLI:
        def scores(self, pairs):
            # Claim's cited evidence entails it; an uncited-context check flags suspicion.
            return [(0.99, 0.01)] + [(0.01, 0.99)] * (len(pairs) - 1)

    pipeline.guard.nli = SuspectNLI()

    async def structured(model, instructions, payload, execution, timeout):
        calls.append(model.__name__)
        if model is Rewrite:
            return Rewrite(queries=["support hours"])
        if model is Generation:
            context = payload["evidence"][0]
            return Generation(
                abstain=False,
                claims=[
                    Claim(
                        text=context["text"],
                        evidence=[Evidence(chunk_id=context["chunk_id"], quote=context["text"])],
                    )
                ],
            )
        assert model is ConflictAssessment
        assert payload["pairs"] == [
            {"pair_id": 0, "claim_index": 0, "suspect_chunk_id": payload["excerpts"][0]["chunk_id"]}
        ]
        assert timeout > 0
        if outcome == "unavailable":
            raise ProviderUnavailable("Synthetic failure")
        return assessment(outcome, document.text if outcome == "contradiction" else None)

    pipeline.gateway.structured = structured
    answer = await pipeline.run(Query(text="support available hours"), principal)
    assert calls == ["Rewrite", "Generation", "ConflictAssessment"]
    assert "conflict_check" in answer.stage_ms
    if outcome == "compatible":
        assert answer.status == "answered"
        assert answer.citations
        assert not answer.review_reasons
    else:
        assert answer.status == "review"
        assert not answer.claims and not answer.citations
        assert "conflicting_context" in answer.review_reasons
        if outcome == "unavailable":
            assert "conflict_check_unavailable" in answer.review_reasons
