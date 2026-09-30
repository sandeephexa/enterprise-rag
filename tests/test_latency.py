"""Latency optimizations preserve permissions, invalidation and verification."""

import time

import pytest

from rag.schemas import Claim, Evidence, Generation, Query, Rewrite


async def test_fallback_rewrite_skips_remote_call_for_relevant_query(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    calls = []

    async def structured(schema, prompt, payload, execution, timeout):
        calls.append(schema.__name__)
        assert schema is Generation
        c = payload["evidence"][0]
        return Generation(
            abstain=False,
            claims=[
                Claim(text=c["text"], evidence=[Evidence(chunk_id=c["chunk_id"], quote=c["text"])])
            ],
        )

    pipeline.gateway.structured = structured
    result = await pipeline.run(Query(text="support available hours"), principal)
    assert result.status == "answered"
    assert calls == ["Generation"]
    assert "rewrite" not in result.stage_ms


async def test_fallback_rewrite_recovers_an_empty_initial_search(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    candidates = pipeline.retriever.candidates
    pipeline.retriever.candidates = lambda queries, actor: (
        [] if len(queries) == 1 else candidates(["support hours"], actor)
    )
    calls = []

    async def structured(schema, prompt, payload, execution, timeout):
        calls.append(schema.__name__)
        if schema is Rewrite:
            return Rewrite(queries=["support hours"])
        c = payload["evidence"][0]
        return Generation(
            abstain=False,
            claims=[
                Claim(text=c["text"], evidence=[Evidence(chunk_id=c["chunk_id"], quote=c["text"])])
            ],
        )

    pipeline.gateway.structured = structured
    result = await pipeline.run(Query(text="support available"), principal)
    assert result.status == "answered"
    assert calls == ["Rewrite", "Generation"]


async def test_cache_has_fresh_trace_usage_and_copies(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    first = await pipeline.run(Query(text="support available hours"), principal)
    assert first.status == "answered" and not first.cache_hit
    first.answer = "caller mutation"
    second = await pipeline.run(Query(text="support available hours"), principal)
    assert second.cache_hit and second.answer != first.answer
    assert second.request_id != first.request_id
    assert second.usage.attempts == second.usage.input_tokens == second.usage.output_tokens == 0
    assert second.usage.known_cost_usd == 0
    assert set(second.stage_ms) == {"cache_lookup"}
    assert second.citations


async def test_cache_invalidates_on_update_delete_and_acl_change(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    query = Query(text="support available hours")
    await pipeline.run(query, principal)
    assert (await pipeline.run(query, principal)).cache_hit
    pipeline.store.ingest(
        [document.model_copy(update={"text": "Support is available 12 hours a day."})], principal
    )
    result = await pipeline.run(query, principal)
    assert not result.cache_hit and "12" in result.answer
    admin = principal.model_copy(update={"groups": ["staff", "restricted"]})
    pipeline.store.ingest([document.model_copy(update={"groups": ["restricted"]})], admin)
    hidden = await pipeline.run(query, principal)
    assert not hidden.cache_hit and not hidden.contexts
    pipeline.store.delete(document.id, admin)
    assert not (await pipeline.run(query, principal)).cache_hit


@pytest.mark.parametrize("change", ["tenant", "groups", "subject", "roles", "policy"])
async def test_cache_is_identity_and_policy_scoped(pipeline, document, principal, change):
    pipeline.store.ingest([document], principal)
    query = Query(text="support available hours")
    await pipeline.run(query, principal)
    actor = principal
    if change == "policy":
        pipeline.settings.entailment_threshold = 0.9
    else:
        actor = principal.model_copy(
            update={
                change: {
                    "tenant": "other",
                    "groups": ["visitor"],
                    "subject": "other-person",
                    "roles": ["query"],
                }[change]
            }
        )
    result = await pipeline.run(query, actor)
    assert not result.cache_hit
    if change in {"tenant", "groups"}:
        assert not result.contexts


async def test_cache_expiry_eviction_disabled_and_no_review_caching(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.answer_cache_max_entries = 1
    first = Query(text="support available hours")
    await pipeline.run(first, principal)
    await pipeline.run(Query(text="available support"), principal)
    assert len(pipeline.answer_cache) == 1
    assert not (await pipeline.run(first, principal)).cache_hit
    key = next(iter(pipeline.answer_cache))
    _, answer = pipeline.answer_cache[key]
    pipeline.answer_cache[key] = (time.monotonic() - 1, answer)
    assert not (await pipeline.run(first, principal)).cache_hit
    pipeline.settings.answer_cache_ttl_s = 0
    assert not (await pipeline.run(first, principal)).cache_hit
    assert not (await pipeline.run(first, principal)).cache_hit
    pipeline.settings.answer_cache_ttl_s = 60
    risk = Query(text="medical support available hours")
    for _ in range(2):
        result = await pipeline.run(risk, principal)
        assert result.status == "review" and not result.cache_hit


def test_revision_is_atomic_and_shared_across_store_instances(settings, document, principal):
    from rag.ingestion import DemoEncoder, HybridStore

    store = HybridStore(settings, DemoEncoder())
    second = HybridStore(settings, DemoEncoder())
    assert second.revision(principal.tenant) == 0
    store.ingest([document], principal)
    assert second.revision(principal.tenant) == 1
    settings.max_chunks_per_tenant = 1
    with pytest.raises(ValueError, match="capacity"):
        store.ingest([document.model_copy(update={"text": document.text * 30})], principal)
    assert second.revision(principal.tenant) == 1
    store.delete(document.id, principal)
    assert second.revision(principal.tenant) == 2
    assert second.revision("other") == 0


def test_nli_batches_deduplicate_without_omitting_checks(settings):
    import threading
    from types import SimpleNamespace

    import numpy as np

    from rag.guardrails import NeuralEntailment

    seen = []

    def predict(pairs, **kwargs):
        seen.append((pairs, kwargs))
        return np.array([[0, 3, 0] if p[0] == "supported" else [3, 0, 0] for p in pairs])

    nli = NeuralEntailment.__new__(NeuralEntailment)
    nli.settings = settings
    nli.lock = threading.Lock()
    nli.model = SimpleNamespace(tokenizer=lambda *a, **k: {"input_ids": [1, 2]}, predict=predict)
    pairs = [("supported", "claim"), ("opposed", "claim"), ("supported", "claim")]
    result = nli.scores(pairs)
    assert len(result) == 3 and result[0] == result[2]
    assert result[0][0] > 0.85 and result[1][1] > 0.85
    assert len(seen[0][0]) == 2 and seen[0][1]["batch_size"] == 4


def test_warmup_initializes_every_execution_thread():
    import threading

    from rag.pipeline import CPUWorkers

    workers = CPUWorkers(2)
    seen = set()
    try:
        workers.warmup(lambda: seen.add(threading.get_ident()))
        assert len(seen) == 2
        assert workers.executor.submit(threading.get_ident).result() in seen
    finally:
        workers.close()


def test_warmup_failure_closes_worker_pool():
    from rag.pipeline import CPUWorkers

    workers = CPUWorkers(2)

    def fail():
        raise ValueError("Model warmup failed")

    with pytest.raises(ValueError, match="warmup"):
        workers.warmup(fail)
    with pytest.raises(RuntimeError, match="shutdown"):
        workers.executor.submit(lambda: None)


def test_reference_spans_preserve_all_source_characters():
    from rag.pipeline import reference_spans

    text = "Heading\nFirst fact. Second fact!\n\nA table: amount\t100\n"
    payload = {"evidence": [{"chunk_id": "S1", "text": text}]}
    wire, references = reference_spans(payload)
    spans = wire["evidence"][0]["spans"]
    assert "".join(span["text"] for span in spans) == text
    assert all(references[span["span_id"]] == ("S1", span["text"]) for span in spans)
    assert payload["evidence"][0]["text"] == text
