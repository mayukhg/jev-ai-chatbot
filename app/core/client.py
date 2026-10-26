"""Asynchronous client for the OpenRouter Decisions API, with a deterministic offline mock."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.core.models import (
    ChoiceQuestion,
    DecisionRequest,
    DecisionResult,
    NoulQuestion,
    ScoreQuestion,
    UpstreamDecisionResponse,
)

RETRYABLE_STATUS = {429, 500, 502, 503, 524, 529}


class JevAPIError(Exception):
    """Raised when the Decisions API returns an error or cannot be reached."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class JevClient:
    """Sends typed Noul / Choice / Score questions to Jev and measures latency.

    When the settings resolve to mock mode, the client will answer locally with
    `MockJevGenerator` and never open a network connection.
    """

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._mock = MockJevGenerator()

    @property
    def mock_mode(self) -> bool:
        return self.settings.effective_mock_mode

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.settings.http_referer,
            "X-Title": self.settings.app_title,
        }

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.request_timeout_s),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                headers=self._headers(),
                transport=self._transport,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    @staticmethod
    def build_payload(request: DecisionRequest) -> dict[str, Any]:
        """Serializes a request into the exact JSON body the Decisions API expects."""
        return request.model_dump(mode="json", by_alias=False)

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        """Executes one multi-question decision call and returns typed answers plus latency."""
        start = time.perf_counter()
        if self.mock_mode:
            response = self._mock.generate(request)
            return DecisionResult(response=response, latency_ms=_elapsed_ms(start), mock=True)

        payload = self.build_payload(request)
        attempts = 0
        last_error: JevAPIError | None = None
        while attempts <= self.settings.max_retries:
            attempts += 1
            try:
                resp = await self._client().post(self.settings.openrouter_decisions_url, json=payload)
            except httpx.TimeoutException as exc:
                last_error = JevAPIError(f"Decisions API timed out: {exc}")
            except httpx.TransportError as exc:
                last_error = JevAPIError(f"Decisions API unreachable: {exc}")
            else:
                if resp.status_code == 200:
                    try:
                        parsed = UpstreamDecisionResponse.model_validate(resp.json())
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise JevAPIError(f"Malformed Decisions API response: {exc}", 200) from exc
                    return DecisionResult(
                        response=parsed, latency_ms=_elapsed_ms(start), mock=False, attempts=attempts
                    )
                last_error = _error_from_response(resp)
                if resp.status_code not in RETRYABLE_STATUS:
                    raise last_error
                retry_after = _retry_after_s(resp)
                if retry_after is not None and attempts <= self.settings.max_retries:
                    await asyncio.sleep(retry_after)
                    continue
            if attempts <= self.settings.max_retries:
                await asyncio.sleep(self.settings.backoff_base_s * (2 ** (attempts - 1)))
        assert last_error is not None
        raise last_error


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _retry_after_s(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if value is None:
        return None
    try:
        return min(float(value), 30.0)
    except ValueError:
        return None


def _error_from_response(resp: httpx.Response) -> JevAPIError:
    try:
        body = resp.json()
        message = body.get("error", {}).get("message") or resp.text
    except (ValueError, AttributeError):
        body, message = resp.text, resp.text
    return JevAPIError(f"Decisions API error {resp.status_code}: {message}", resp.status_code, body)


# --------------------------------------------------------------------------- mock generator

_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "are", "was", "but", "not", "you", "your",
    "our", "has", "have", "had", "can", "will", "its", "from", "they", "them", "been", "into",
    "any", "all", "out", "about", "would", "there", "their", "what", "when", "which", "who",
}
_VAGUE_CUES = {"vague", "ambig", "incom", "missi", "unclear", "short", "lacki", "insuf"}


def _flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(f"{k} {_flatten(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _stems(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:5] for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _noise(*parts: str) -> float:
    """Deterministic pseudo-random value in [0, 1) derived from the inputs."""
    digest = hashlib.sha256("\x1f".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _softmax(scores: list[float], temperature: float) -> list[float]:
    peak = max(scores)
    exps = [math.exp((s - peak) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


class MockJevGenerator:
    """Produces deterministic, plausibly calibrated answers without calling the network.

    Options whose guidance shares vocabulary with the state will receive more
    probability mass; a hash of the inputs adds stable tie-breaking noise. The
    same request will always yield the same answers.
    """

    def generate(self, request: DecisionRequest) -> UpstreamDecisionResponse:
        state_text = _flatten(request.state)
        state_stems = _stems(state_text)
        word_count = len(re.findall(r"\w+", state_text))
        answers: dict[str, Any] = {}
        for key, question in request.questions.items():
            seed = f"{key}|{state_text}"
            if isinstance(question, ChoiceQuestion):
                answers[key] = self._choice(question, state_stems, seed)
            elif isinstance(question, ScoreQuestion):
                answers[key] = self._score(question, state_stems, seed)
            elif isinstance(question, NoulQuestion):
                answers[key] = self._noul(question, state_stems, word_count, seed)
        digest = hashlib.sha256(json.dumps(JevClient.build_payload(request), sort_keys=True).encode()).hexdigest()[:16]
        return UpstreamDecisionResponse.model_validate(
            {
                "id": f"mock-{digest}",
                "model": request.model,
                "provider": "mock",
                "answers": answers,
                "usage": {"input_tokens": max(1, len(state_text) // 4), "output_tokens": 0, "cost": 0.0},
            }
        )

    @staticmethod
    def _overlap(stems: set[str], *texts: Any) -> float:
        guidance = _stems(" ".join(_flatten(t) for t in texts))
        return float(len(stems & guidance))

    def _choice(self, q: ChoiceQuestion, stems: set[str], seed: str) -> dict[str, Any]:
        labels = list(q.criteria)
        raw = [
            self._overlap(stems, label, q.criteria[label]) + 0.6 * _noise(seed, label)
            for label in labels
        ]
        probs = _softmax(raw, temperature=0.55)
        probabilities = {label: round(p, 4) for label, p in zip(labels, probs)}
        best = max(probabilities, key=probabilities.get)
        return {
            "type": "choice",
            "choice": best,
            "confidence": probabilities[best],
            "probabilities": probabilities,
        }

    def _score(self, q: ScoreQuestion, stems: set[str], seed: str) -> dict[str, Any]:
        raw = [
            self._overlap(stems, level) + 0.8 * _noise(seed, str(i)) for i, level in enumerate(q.criteria)
        ]
        probs = _softmax(raw, temperature=0.7)
        probabilities = {str(i): round(p, 4) for i, p in enumerate(probs)}
        expected = sum(i * p for i, p in enumerate(probs))
        return {
            "type": "score",
            "score": round(expected, 4),
            "confidence": round(max(probs), 4),
            "probabilities": probabilities,
            "legend": {str(i): level for i, level in enumerate(q.criteria)},
        }

    def _noul(self, q: NoulQuestion, stems: set[str], word_count: int, seed: str) -> dict[str, Any]:
        true_text = _flatten([q.instructions, q.criteria.true])
        margin = self._overlap(stems, q.criteria.true) - self._overlap(stems, q.criteria.false)
        # Questions about vagueness or missing detail will lean true for very short inputs.
        if _stems(true_text) & _VAGUE_CUES:
            margin += 2.0 if word_count < 8 else -1.5
        margin += _noise(seed, "noul") - 0.5
        return {"type": "noul", "noul": round(1 / (1 + math.exp(-margin)), 4)}

