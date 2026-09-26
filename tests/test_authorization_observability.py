import json
import logging

import httpx

from rag.app import create_app
from rag.config import AccessKey
from rag.schemas import Principal, Query, ReviewDecision

from .conftest import TOKEN


async def test_query_only_cannot_ingest(settings, pipeline, document):
    settings.access_keys = [
        AccessKey(token=TOKEN, tenant="acme", groups=["staff"], roles=["query"])
    ]
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/ingest",
            headers={"Authorization": "Bearer " + TOKEN},
            json={"documents": [document.model_dump()]},
        )
        assert response.status_code == 403


async def test_review_isolation_and_decision(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    answer = await pipeline.run(Query(text="medical support available hours"), principal)
    for other in [
        Principal(tenant="other", groups=["staff"], roles=["review"]),
        Principal(tenant="acme", groups=[], roles=["review"]),
    ]:
        assert pipeline.store.reviews(other) == []
        assert not pipeline.store.decide(
            answer.request_id, ReviewDecision(decision="approve", note="test"), other
        )


async def test_redacted_logs_and_chunked_body_limit(settings, pipeline, caplog):
    settings.max_body_bytes = 1024
    app = create_app(settings, pipeline, telemetry=False)
    with caplog.at_level(logging.INFO, logger="rag.audit"):
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):

            async def body():
                yield b"x" * 800
                yield b"x" * 800

            response = await client.post(
                "/query", content=body(), headers={"Authorization": "Bearer " + TOKEN}
            )
            assert response.status_code == 413
            await client.post(
                "/query",
                json={"text": "confidential project aardvark"},
                headers={"Authorization": "Bearer " + TOKEN},
            )
    audit = [json.loads(record.message) for record in caplog.records if record.name == "rag.audit"]
    assert audit and all("trace_id" in item for item in audit)
    assert TOKEN not in caplog.text
    assert "aardvark" not in caplog.text
