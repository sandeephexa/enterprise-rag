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


@pytest.mark.parametrize("compact", [True, False])
async def test_short_evidence_ids_restore_canonical_sources(settings, compact):
    from copy import deepcopy

    from rag.schemas import Generation

    settings.endpoints = [endpoint()]
    settings.compact_evidence_ids = compact
    original_id = "private-document-version-" + "a" * 64
    payload = {
        "question": "When is support available?",
        "evidence": [{"chunk_id": original_id, "text": "Support is available daily."}],
        "previous_draft": {
            "claims": [
                {
                    "text": "Support is available daily.",
                    "evidence": [{"chunk_id": original_id, "quote": "Support is available daily."}],
                }
            ]
        },
    }
    untouched = deepcopy(payload)

    def handler(request):
        body = json.loads(request.content)
        data = json.loads(body["input"])
        alias = "S1" if compact else original_id
        assert data["evidence"][0]["chunk_id"] == alias
        assert data["previous_draft"]["claims"][0]["evidence"][0]["chunk_id"] == alias
        assert data["evidence"][0]["text"] == payload["evidence"][0]["text"]
        return httpx.Response(
            200,
            json=completed(
                json.dumps(
                    {
                        "abstain": False,
                        "claims": [
                            {
                                "text": "Support is available daily.",
                                "evidence": [
                                    {"chunk_id": alias, "quote": "Support is available daily."},
                                    {"chunk_id": "invented", "quote": "Fake source"},
                                ],
                            }
                        ],
                    }
                )
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelGateway(settings, client).structured(
            Generation, "Answer using supplied evidence", payload, Execution(settings), 10
        )
    assert result.claims[0].evidence[0].chunk_id == original_id
    assert result.claims[0].evidence[1].chunk_id == "invented"
    assert payload == untouched


@pytest.mark.parametrize("unknown", [False, True])
async def test_span_references_are_resolved_only_from_supplied_sources(settings, unknown):
    from rag.schemas import Generation

    settings.endpoints = [endpoint()]
    settings.generation_evidence_mode = "spans"
    payload = {"evidence": [{"chunk_id": "canonical-123", "text": "Support is available daily."}]}

    def handler(request):
        body = json.loads(request.content)
        assert body["text"]["format"]["name"] == "ReferencedGeneration"
        return httpx.Response(
            200,
            json=completed(
                json.dumps(
                    {
                        "abstain": False,
                        "claims": [
                            {
                                "text": "Support is available daily.",
                                "source_ids": ["S99"] if unknown else ["S1.1", "S1.1"],
                            }
                        ],
                    }
                )
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(settings, client)
        if unknown:
            with pytest.raises(ProviderUnavailable):
                await gateway.structured(Generation, "answer", payload, Execution(settings), 10)
        else:
            result = await gateway.structured(
                Generation, "answer", payload, Execution(settings), 10
            )
            assert len(result.claims[0].evidence) == 1
            assert result.claims[0].evidence[0].chunk_id == "canonical-123"
            assert result.claims[0].evidence[0].quote == payload["evidence"][0]["text"]


async def test_long_passages_use_quote_contract_without_truncation(settings):
    from rag.schemas import Generation

    settings.endpoints = [endpoint()]
    settings.generation_evidence_mode = "spans"
    passage = "word " * 500

    def handler(request):
        body = json.loads(request.content)
        assert body["text"]["format"]["name"] == "Generation"
        assert json.loads(body["input"])["evidence"][0]["text"] == passage
        return httpx.Response(200, json=completed('{"abstain":true,"claims":[]}'))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ModelGateway(settings, client).structured(
            Generation,
            "answer",
            {"evidence": [{"chunk_id": "id", "text": passage}]},
            Execution(settings),
            10,
        )
    assert result.abstain


@pytest.mark.parametrize("operation", ["generate", "repair", "rewrite"])
async def test_reasoning_tuning_applies_only_to_initial_generation(settings, operation):
    from rag.schemas import Generation

    settings.endpoints = [endpoint()]
    settings.generation_reasoning_effort = "none"
    model = Rewrite if operation == "rewrite" else Generation
    payload = {"previous_draft": {}} if operation == "repair" else {}

    def handler(request):
        body = json.loads(request.content)
        if operation == "generate":
            assert body["reasoning"] == {"effort": "none"}
        else:
            assert "reasoning" not in body
        content = (
            '{"queries":["search"]}' if operation == "rewrite" else '{"abstain":true,"claims":[]}'
        )
        return httpx.Response(200, json=completed(content))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ModelGateway(settings, client).structured(
            model, "prompt", payload, Execution(settings), 10
        )


@pytest.mark.parametrize("selection", ["valid", "unknown", "abstain", "inconsistent"])
async def test_extractive_selection_constructs_only_exact_source_claims(settings, selection):
    from rag.schemas import Generation

    settings.answer_style = "extractive"
    settings.endpoints = [endpoint()]
    text = "The position includes related\nduties assigned by supervisors."
    payload = {"evidence": [{"chunk_id": "canonical", "text": text}]}

    def handler(request):
        body = json.loads(request.content)
        assert body["text"]["format"]["name"] == "EvidenceSelection"
        data = json.loads(body["input"])
        assert len(data["evidence"][0]["spans"]) == 1  # PDF line wrap is not a new sentence.
        result = {
            "abstain": selection == "abstain",
            "source_ids": []
            if selection in {"abstain", "inconsistent"}
            else ["S1.1" if selection == "valid" else "S9.9"],
        }
        return httpx.Response(200, json=completed(json.dumps(result)))

    execution = Execution(settings)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ModelGateway(settings, client)
        if selection in {"unknown", "inconsistent"}:
            with pytest.raises(ProviderUnavailable):
                await gateway.structured(Generation, "answer", payload, execution, 10)
        else:
            output = await gateway.structured(Generation, "answer", payload, execution, 10)
            assert execution.answer_style == "extractive"
            if selection == "valid":
                assert output.claims[0].text == text
                assert output.claims[0].evidence[0].quote == text
                assert output.claims[0].evidence[0].chunk_id == "canonical"
            else:
                assert output.abstain and not output.claims
