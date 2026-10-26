import json

import httpx
import pytest

from app.core.client import JevAPIError, JevClient
from app.core.config import Settings
from app.core.models import DecisionRequest

REQUEST = DecisionRequest.model_validate(
    {
        "model": "typesafe/jev-1.14",
        "state": "I was charged twice for my invoice and need a refund.",
        "questions": {
            "category": {
                "type": "choice",
                "instructions": "Categorize the ticket",
                "criteria": {"billing": "Invoices, payments, refunds", "technical": "Bugs and crashes"},
            },
            "urgency": {"type": "score", "instructions": "Rate urgency", "scale": ["P4 Low", "P1 Critical"]},
            "ambiguous": {"type": "noul", "instructions": "Is this request ambiguous?"},
        },
    }
)

UPSTREAM_OK = {
    "id": "dec-123",
    "model": "typesafe/jev-1.14",
    "provider": "TypeSafe",
    "answers": {
        "category": {"type": "choice", "choice": "billing", "confidence": 0.91, "probabilities": {"billing": 0.91, "technical": 0.09}},
        "urgency": {"type": "score", "score": 0.3, "confidence": 0.7, "probabilities": {"0": 0.7, "1": 0.3}, "legend": {"0": "P4 Low", "1": "P1 Critical"}},
        "ambiguous": {"type": "noul", "noul": 0.12},
    },
    "usage": {"input_tokens": 120, "output_tokens": 0, "cost": 0.00004},
}


def test_payload_serialization_matches_decisions_api():
    payload = JevClient.build_payload(REQUEST)
    assert payload["model"] == "typesafe/jev-1.14"
    assert payload["questions"]["urgency"] == {"type": "score", "instructions": "Rate urgency", "criteria": ["P4 Low", "P1 Critical"]}
    assert set(payload["questions"]["ambiguous"]["criteria"]) == {"true", "false"}
    assert payload["questions"]["category"]["criteria"]["billing"].startswith("Invoices")
    json.dumps(payload)  # will be JSON-serializable


def test_placeholder_credentials_force_mock_mode():
    settings = Settings(_env_file=None, mock_mode=False)
    assert settings.has_placeholder_credentials
    assert settings.effective_mock_mode
    assert settings.setup_notice().startswith("[SETUP NOTICE]")
    assert not Settings(_env_file=None, openrouter_api_key="sk-or-real").effective_mock_mode


async def test_mock_responses_are_deterministic_and_well_formed(mock_settings):
    client = JevClient(mock_settings)
    first, second = await client.decide(REQUEST), await client.decide(REQUEST)
    assert first.mock is True
    assert first.response.answers == second.response.answers
    category = first.response.answers["category"]
    assert category.choice == "billing"
    assert sum(category.probabilities.values()) == pytest.approx(1, abs=1e-3)
    assert 0 <= first.response.answers["ambiguous"].noul <= 1
    assert first.latency_ms >= 0


async def test_live_call_sends_headers_and_parses_response(live_settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=UPSTREAM_OK)

    client = JevClient(live_settings, transport=httpx.MockTransport(handler))
    result = await client.decide(REQUEST)
    await client.aclose()

    assert result.mock is False
    assert result.response.answers["category"].confidence == 0.91
    assert result.response.usage.cost == 0.00004
    assert seen["headers"]["authorization"] == "Bearer sk-or-test-key"
    assert seen["headers"]["x-title"] == "Jev Decision Engine Workbench"
    assert seen["headers"]["http-referer"] == "http://localhost:8000"
    assert seen["body"]["questions"]["urgency"]["criteria"] == ["P4 Low", "P1 Critical"]


async def test_retries_on_429_then_succeeds(live_settings):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"code": 429, "message": "rate limited"}})
        return httpx.Response(200, json=UPSTREAM_OK)

    client = JevClient(live_settings, transport=httpx.MockTransport(handler))
    result = await client.decide(REQUEST)
    assert result.attempts == 3
    assert len(calls) == 3


async def test_non_retryable_error_raises_immediately(live_settings):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"code": 401, "message": "No auth credentials found"}})

    client = JevClient(live_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(JevAPIError) as exc:
        await client.decide(REQUEST)
    assert exc.value.status_code == 401
    assert "No auth credentials" in str(exc.value)
    assert len(calls) == 1


async def test_persistent_5xx_exhausts_retries(live_settings):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="unavailable")

    client = JevClient(live_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(JevAPIError) as exc:
        await client.decide(REQUEST)
    assert exc.value.status_code == 503
    assert len(calls) == live_settings.max_retries + 1


async def test_timeout_is_reported(live_settings):
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = JevClient(live_settings, transport=httpx.MockTransport(handler))
    with pytest.raises(JevAPIError, match="timed out"):
        await client.decide(REQUEST)
