import numpy as np
import pytest

from rag.ingestion import Chunker, DemoEncoder, HybridStore
from rag.retriever import assemble_context, bm25
from rag.schemas import Document, Principal


@pytest.mark.parametrize("strategy", ["sentence", "paragraph", "semantic"])
def test_chunk_offsets_and_coverage(settings, strategy):
    cfg = settings.model_copy(
        update={"chunk_strategy": strategy, "chunk_chars": 120, "overlap_chars": 20}
    )
    text = (
        "A sentence about support. Another sentence about pricing.\n\n" * 15
    ) + "unbrokentext" * 30
    doc = Document(id="offsets", title="Offsets", source="urn:test", text=text, groups=["staff"])
    chunks = Chunker(cfg, DemoEncoder()).split(doc, "acme")
    covered = set()
    for chunk in chunks:
        assert chunk.text == text[chunk.start : chunk.end]
        assert len(chunk.text) <= cfg.chunk_chars
        covered.update(range(chunk.start, chunk.end))
    assert all(index in covered for index, char in enumerate(text) if not char.isspace())


async def test_persistence_idempotency_and_tenant_acl(pipeline, settings, document, principal):
    count = pipeline.store.ingest([document], principal)
    assert pipeline.store.ingest([document], principal) == count
    reloaded = HybridStore(settings, DemoEncoder())
    assert len(reloaded.snapshot(principal)[0]) == count
    for other in [
        Principal(tenant="other", groups=["staff"], roles=[]),
        Principal(tenant="acme", groups=["visitor"], roles=[]),
    ]:
        assert pipeline.retriever.candidates(["support"], other) == []
    assert pipeline.retriever.candidates(["support"], principal)


async def test_update_is_atomic_on_capacity_failure(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    original = pipeline.store.snapshot(principal)[0]
    pipeline.store.settings.max_chunks_per_tenant = 1
    replacement = document.model_copy(update={"text": "Replacement support statement. " * 100})
    with pytest.raises(ValueError, match="capacity"):
        pipeline.store.ingest([replacement], principal)
    assert pipeline.store.snapshot(principal)[0] == original


async def test_update_delete_and_embedding_identity(pipeline, document, principal, settings):
    pipeline.store.ingest([document], principal)
    old = pipeline.store.snapshot(principal)[0][0]
    pipeline.store.ingest(
        [document.model_copy(update={"text": "Support is now available weekdays only."})], principal
    )
    new = pipeline.store.snapshot(principal)[0][0]
    assert new.version != old.version
    assert new.id != old.id
    encoder = DemoEncoder()
    encoder.identity = "incompatible"
    with pytest.raises(ValueError, match="identity"):
        HybridStore(settings, encoder)
    assert pipeline.store.delete(document.id, principal.tenant) == 1
    assert not pipeline.store.snapshot(principal)[0]


def test_bm25_and_missing_terms():
    scores = bm25("support", [["support", "support"], ["billing"]])
    assert scores[0] > scores[1] == 0
    assert bm25("absent", [["support"]]) == [0]


async def test_dynamic_k_can_be_zero(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    hits = pipeline.retriever.candidates(["support"], principal)
    assert pipeline.retriever.rerank("unrelated nonsense", hits) == []
    selected = pipeline.retriever.rerank("support available", hits)
    assert selected and len(selected) <= pipeline.settings.max_top_k
    assert assemble_context(selected, 1) == []


async def test_document_subject_survives_reranking_without_altering_evidence(pipeline, principal):
    doc = Document(
        id="resume",
        title="Alex resume",
        source="urn:test:resume",
        text="Developed services using Python.",
        groups=["staff"],
    )
    pipeline.store.ingest([doc], principal)
    # The subject appears only in document metadata, not in this passage.
    hits = pipeline.retriever.candidates(["Python"], principal)
    selected = pipeline.retriever.rerank("Alex Python", hits)
    assert len(selected) == 1
    chunk = selected[0].chunk
    assert chunk.text == doc.text[chunk.start : chunk.end]
    assert "Alex" not in chunk.text


async def test_vector_semantics_branch_independent_of_bm25(pipeline, principal):
    # Inject known vectors to prove synonym retrieval even with no shared keyword.
    class SynonymEncoder:
        identity = "controlled-test-vectors"

        def encode(self, texts):
            return np.array(
                [[1, 0] if "car" in text or "vehicle" in text else [0, 1] for text in texts],
                dtype=np.float32,
            )

    pipeline.store.encoder = SynonymEncoder()
    pipeline.retriever.encoder = pipeline.store.encoder
    doc = Document(
        id="car",
        title="Vehicle",
        text="A vehicle needs maintenance.",
        source="urn:test:car",
        groups=["staff"],
    )
    pipeline.store.ingest([doc], principal)
    assert bm25("car", [["vehicle", "maintenance"]]) == [0]
    hits = pipeline.retriever.candidates(["car"], principal)
    assert hits[0].chunk.document_id == "car"
