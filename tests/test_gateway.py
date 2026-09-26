import asyncio
import json

import httpx
import pytest

from rag.config import Endpoint
from rag.pipeline import BudgetExceeded, Execution, ModelGateway, PolicyRefusal, ProviderUnavailable
from rag.schemas import Rewrite


def endpoint(name="primary"):
    return Endpoint(
        name=name,
        base_url=f"https://{name}.example/v1",
        api_key="test-secret",
        model="configured-model",
        input_usd_per_million=1,
        output_usd_per_million=2,
    )


def completed(text='{"queries":["support hours"]}'):
    return {
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


async def test_retry_after_and_fallback_usage(settings, monkeypatch):
    calls = []
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def handler(request):
        calls.append(request.url.host)
        assert json.loads(request.content)["store"] is False
        if request.url.host == "primary.example":
            return httpx.Response(429, headers={"Retry-After": "0.3"})
        return httpx.Response(200, json=completed())

    settings.endpoints = [endpoint(), endpoint("fallback")]
    execution = Execution(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelGateway(settings, client).structured(
            Rewrite, "rewrite", {}, execution, 10
        )
    assert result.queries == ["support hours"]
    assert calls == ["primary.example", "primary.example", "fallback.example"]
    assert waits[0] >= 0.3
    assert execution.usage.input_tokens == 100
    assert execution.usage.output_tokens == 20
    assert execution.usage.uncertain_attempts == 2
    assert execution.usage.reserved_cost_usd > 0
    assert execution.usage.known_cost_usd == pytest.approx(0.00014)


async def test_invalid_output_counts_usage_and_falls_back(settings):
    settings.endpoints = [endpoint(), endpoint("fallback")]

    def handler(request):
        return httpx.Response(
            200,
            json=completed(
                "invalid-json" if request.url.host == "primary.example" else '{"queries":["valid"]}'
            ),
        )

    execution = Execution(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelGateway(settings, client).structured(
            Rewrite, "rewrite", {}, execution, 10
        )
    assert result.queries == ["valid"]
    assert execution.usage.input_tokens == 200
    assert execution.usage.uncertain_attempts == 0


async def test_refusal_never_uses_fallback(settings):
    settings.endpoints = [endpoint(), endpoint("fallback")]
    calls = []

    def handler(request):
        calls.append(request)
        data = completed()
        data["output"][0]["content"] = [{"type": "refusal", "refusal": "Policy"}]
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PolicyRefusal):
            await ModelGateway(settings, client).structured(
                Rewrite, "rewrite", {}, Execution(settings), 10
            )
    assert len(calls) == 1


async def test_cost_gate_prevents_request(settings):
    settings.endpoints = [endpoint()]
    settings.max_cost_usd = 0.000001

    def handler(request):
        pytest.fail("Should not call provider")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BudgetExceeded, match="Cost"):
            await ModelGateway(settings, client).structured(
                Rewrite, "rewrite", {}, Execution(settings), 10
            )


async def test_deadline_and_unauthorized_not_retried(settings):
    settings.endpoints = [endpoint()]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(settings, client)
        with pytest.raises(BudgetExceeded):
            await gateway.structured(Rewrite, "rewrite", {}, Execution(settings), 0)
        with pytest.raises(ProviderUnavailable):
            await gateway.structured(Rewrite, "rewrite", {}, Execution(settings), 10)
    assert len(calls) == 1
