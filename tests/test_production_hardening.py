import json
import logging
import math
import random
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import numpy as np
import pytest

from rag.app import create_app
from rag.ingestion import words
from rag.retriever import BM25Index
from rag.schemas import Principal

from .conftest import TOKEN


async def test_json_ingestion_and_delete_enforce_groups(settings, pipeline, document, principal):
    restricted = document.model_copy(update={"groups": ["finance"]})
    admin = principal.model_copy(update={"groups": ["staff", "finance"]})
    pipeline.store.ingest([restricted], admin)
    revision = pipeline.store.revision(principal.tenant)
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        for doc in [restricted.model_copy(update={"id": "new"}), document]:
            response = await client.post("/ingest", json={"documents": [doc.model_dump()]})
            assert response.status_code == 403
        response = await client.delete(f"/documents/{document.id}")
        assert response.status_code == 403
        assert pipeline.store.revision(principal.tenant) == revision
        assert pipeline.store.snapshot(admin)[0][0].groups == ["finance"]
        # Missing documents remain idempotent and cross-tenant IDs remain invisible.
        assert (await client.delete("/documents/missing")).json() == {"deleted_chunks": 0}


async def test_partial_group_access_cannot_relabel_or_delete(pipeline, principal, document):
    admin = principal.model_copy(update={"groups": ["staff", "finance"]})
    protected = document.model_copy(update={"groups": ["staff", "finance"]})
    pipeline.store.ingest([protected], admin)
    assert pipeline.store.snapshot(principal)[
        0
    ]  # Read access does not imply full mutation authority.
    with pytest.raises(PermissionError):
        pipeline.store.delete(document.id, principal)
    with pytest.raises(PermissionError):
        pipeline.store.ingest([document], principal)
    assert pipeline.store.delete(document.id, admin) > 0


async def test_denied_batch_replacement_rolls_back(pipeline, principal, document):
    admin = principal.model_copy(update={"groups": ["staff", "finance"]})
    protected = document.model_copy(update={"id": "restricted", "groups": ["finance"]})
    pipeline.store.ingest([document, protected], admin)
    original = pipeline.store.snapshot(admin)[0]
    revision = pipeline.store.revision(principal.tenant)
    with pytest.raises(PermissionError):
        pipeline.store.ingest(
            [
                document.model_copy(update={"text": "Changed support policy."}),
                protected.model_copy(update={"groups": ["staff"]}),
            ],
            principal,
        )
    assert pipeline.store.snapshot(admin)[0] == original
    assert pipeline.store.revision(principal.tenant) == revision


async def test_review_limit_applies_after_authorization(pipeline, principal):
    with pipeline.store.connect() as db:
        db.executemany(
            "INSERT INTO reviews(request_id,tenant,groups_json,payload,created_at) VALUES(?,?,?,?,?)",
            [
                (f"hidden-{i:03}", "acme", '["finance"]', '{"secret":true}', "2030-01-01")
                for i in range(110)
            ]
            + [(f"visible-{i:03}", "acme", '["staff"]', "{}", "2029-01-01") for i in range(105)],
        )
    rows = pipeline.store.reviews(principal)
    assert len(rows) == 100
    assert rows[0]["request_id"] == "visible-104"
    assert all(row["request_id"].startswith("visible-") for row in rows)
    assert pipeline.store.reviews(Principal(tenant="other", groups=["staff"], roles=[])) == []


async def test_startup_failure_shuts_down_exporters(settings, monkeypatch):
    providers = [SimpleNamespace(shutdown=Mock()), SimpleNamespace(shutdown=Mock())]
    monkeypatch.setattr("rag.app.configure_telemetry", lambda _: providers)
    monkeypatch.setattr("rag.app.build_pipeline", Mock(side_effect=RuntimeError("startup failed")))
    app = create_app(settings)
    with pytest.raises(RuntimeError, match="startup failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("Failed initialization cannot report readiness")
    for provider in providers:
        provider.shutdown.assert_called_once()


async def test_close_failure_does_not_skip_other_resources(settings, monkeypatch):
    provider = SimpleNamespace(shutdown=Mock())
    service = SimpleNamespace(
        gateway=SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("close failed"))),
        workers=SimpleNamespace(close=Mock()),
    )
    monkeypatch.setattr("rag.app.configure_telemetry", lambda _: [provider])
    app = create_app(settings, service)
    with pytest.raises(RuntimeError, match="close failed"):
        async with app.router.lifespan_context(app):
            pass
    provider.shutdown.assert_called_once()
    service.workers.close.assert_called_once()


async def test_unexpected_failure_is_redacted_and_correlated(settings, pipeline, caplog):
    app = create_app(settings, pipeline, telemetry=False)

    @app.get("/test-error")
    async def fail():
        raise KeyError("sensitive-input-must-not-be-logged")

    with caplog.at_level(logging.INFO, logger="rag.audit"):
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            response = await client.get("/test-error")
    assert response.status_code == 500
    assert response.headers["x-request-id"] and response.headers["x-trace-id"]
    assert "sensitive-input" not in response.text + caplog.text
    errors = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "rag.audit" and '"http_error"' in r.message
    ]
    assert errors[0]["error_type"] == "KeyError"


def reference_bm25(query, corpus):
    if not corpus:
        return []
    frequency = Counter(term for doc in corpus for term in set(doc))
    average = sum(map(len, corpus)) / len(corpus) or 1
    scores = []
    for doc in corpus:
        counts = Counter(doc)
        scores.append(
            sum(
                math.log(1 + (len(corpus) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                * counts[term]
                * 2.5
                / (counts[term] + 1.5 * (0.25 + 0.75 * len(doc) / average))
                for term in set(words(query))
            )
        )
    return scores


def test_optimized_bm25_matches_reference_for_rewrites():
    rng = random.Random(4)
    corpus = [
        rng.choices(["support", "billing", "python", "service"], k=rng.randrange(0, 60))
        for _ in range(250)
    ]
    lexical = BM25Index(corpus)
    for query in ["support service", "billing python python", "unknown", "", "SUPPORT"]:
        assert lexical.score(query) == pytest.approx(reference_bm25(query, corpus), abs=1e-12)
    assert BM25Index([]).score("support") == []


async def test_bounded_fusion_selection_preserves_rankings(pipeline, principal, document):
    docs = [
        document.model_copy(update={"id": f"doc-{i}", "text": f"Support billing service {i % 4}."})
        for i in range(50)
    ]
    pipeline.store.ingest(docs, principal)
    queries = ["support", "billing service", "absent"]
    chunks, vectors, corpus = pipeline.store.snapshot(principal)
    fusion = Counter()
    for query, vector in zip(queries, pipeline.retriever.encoder.encode(queries), strict=True):
        for scores in [vectors @ vector, reference_bm25(query, corpus)]:
            order = sorted(range(len(scores)), key=lambda i: (-scores[i], chunks[i].id))
            for rank, index in enumerate(
                [i for i in order if scores[i] > 0][: pipeline.settings.candidate_k], 1
            ):
                fusion[index] += 1 / (60 + rank)
    expected = sorted(fusion, key=lambda i: (-fusion[i], chunks[i].id))[
        : pipeline.settings.candidate_k
    ]
    actual = pipeline.retriever.candidates(queries, principal)
    assert [h.chunk.id for h in actual] == [chunks[i].id for i in expected]
    np.testing.assert_allclose([h.fusion_score for h in actual], [fusion[i] for i in expected])


@pytest.mark.parametrize(
    "url",
    [
        "https://",
        "http://provider.test",
        "https://user:password@provider.test",
        "https://provider.test?key=value",
        "https://provider.test#fragment",
        "https://provider.test:bad",
        "https://provider.test:0",
    ],
)
def test_endpoint_rejects_ambiguous_or_credential_bearing_urls(url):
    from rag.config import Endpoint

    with pytest.raises(ValueError):
        Endpoint(
            name="test",
            base_url=url,
            api_key="test",
            model="test",
            input_usd_per_million=1,
            output_usd_per_million=1,
        )


def test_endpoint_rejects_nonfinite_pricing():
    from rag.config import Endpoint

    with pytest.raises(ValueError):
        Endpoint(
            name="test",
            api_key="test",
            model="test",
            input_usd_per_million=float("inf"),
            output_usd_per_million=1,
        )
