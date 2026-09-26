"""Exercise the live orchestration path with controlled HTTP responses, never API secrets."""

import json

import httpx
import pytest

from rag.config import Endpoint
from rag.pipeline import ModelGateway
from rag.schemas import Query


async def test_live_rewrite_generation_and_verification(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    pipeline.settings.endpoints = [
        Endpoint(
            name="test",
            api_key="test",
            model="test",
            input_usd_per_million=1,
            output_usd_per_million=2,
        )
    ]
    called = []

    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body["input"])
        schema = body["text"]["format"]["name"]
        called.append(schema)
        if schema == "Rewrite":
            result = {"queries": ["Enterprise support hours"]}
        else:
            context = payload["evidence"][0]
            result = {
                "abstain": False,
                "claims": [
                    {
                        "text": context["text"],
                        "evidence": [{"chunk_id": context["chunk_id"], "quote": context["text"]}],
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 50, "output_tokens": 20},
                "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}],
            },
        )

    await pipeline.gateway.close()
    pipeline.gateway = ModelGateway(
        pipeline.settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    answer = await pipeline.run(Query(text="support available hours"), principal)
    assert answer.status == "answered"
    assert called == ["Rewrite", "Generation"]
    assert answer.usage.input_tokens == 100
    assert answer.usage.known_cost_usd == pytest.approx(0.00018)
    assert {"rewrite", "retrieve", "rerank", "generate", "verify"}.issubset(answer.stage_ms)


async def test_live_hallucination_routes_to_durable_review(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.mode = "live"
    pipeline.settings.endpoints = [
        Endpoint(
            name="test",
            api_key="test",
            model="test",
            input_usd_per_million=1,
            output_usd_per_million=2,
        )
    ]

    def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body["input"])
        if body["text"]["format"]["name"] == "Rewrite":
            result = {"queries": ["support hours"]}
        else:
            context = payload["evidence"][0]
            result = {
                "abstain": False,
                "claims": [
                    {
                        "text": "Support costs one million dollars.",
                        "evidence": [{"chunk_id": context["chunk_id"], "quote": context["text"]}],
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 50, "output_tokens": 20},
                "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}],
            },
        )

    await pipeline.gateway.close()
    pipeline.gateway = ModelGateway(
        pipeline.settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    answer = await pipeline.run(Query(text="support available hours"), principal)
    assert answer.status == "review"
    assert answer.claims == []
    review = pipeline.store.reviews(principal)[0]["answer"]
    assert review["question"] == "support available hours"
    assert review["verified_draft"] is None


async def test_total_deadline_causes_abstention(pipeline, document, principal):
    pipeline.store.ingest([document], principal)
    pipeline.settings.latency_budget_s = 0.001
    answer = await pipeline.run(Query(text="support hours"), principal)
    assert answer.status == "abstained"
    assert "budget_exhausted" in answer.review_reasons
    assert answer.latency_ms < 100
