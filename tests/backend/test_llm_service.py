"""
Tests for the LLM service layer.

Every Gemini call is mocked with httpx.MockTransport — no real API calls are made.
"""

import json
import logging

import httpx
import pytest

from app.core.config import settings
from app.services.gemini_llm_service import API_BASE_URL, DEFAULT_MODEL, GeminiLLMService
from app.services.llm_service import (
    LLMRateLimitError,
    LLMServiceError,
    LLMTimeoutError,
    MockLLMService,
    get_llm_service,
)

API_KEY = "test-gemini-key-1234"
PROMPT = "What is photosynthesis?"


def _success_body(text: str = "Plants convert light into energy.") -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def _service(handler, **kwargs) -> GeminiLLMService:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GeminiLLMService(api_key=API_KEY, http_client=client, **kwargs)


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------

def test_mock_is_default_when_provider_unset(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "")
    assert isinstance(get_llm_service(), MockLLMService)


def test_mock_is_used_for_explicit_mock(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    assert isinstance(get_llm_service(), MockLLMService)


def test_gemini_provider_is_selected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_MODEL", "gemini-3.8-flash")
    service = get_llm_service()
    assert isinstance(service, GeminiLLMService)
    assert service.model == "gemini-3.8-flash"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    with pytest.raises(ValueError):
        get_llm_service()


def test_mock_returns_text():
    answer = MockLLMService().generate(PROMPT)
    assert isinstance(answer, str) and answer


# --------------------------------------------------------------------------
# Gemini request / response handling
# --------------------------------------------------------------------------

def test_generate_sends_key_in_header_not_body():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_success_body())

    service = _service(handler, model="gemini-test-model")
    answer = service.generate(PROMPT, system_prompt="Answer briefly.")

    assert answer == "Plants convert light into energy."
    assert captured["url"] == f"{API_BASE_URL}/models/gemini-test-model:generateContent"
    assert captured["headers"]["x-goog-api-key"] == API_KEY
    assert API_KEY not in json.dumps(captured["body"])
    assert captured["body"]["contents"][0]["parts"][0]["text"] == PROMPT
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "Answer briefly."


def test_default_model_is_free_tier_gemini(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "")
    service = GeminiLLMService(api_key=API_KEY, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=_success_body()))
    ))
    assert service.model == DEFAULT_MODEL == "gemini-4-hydrogen"


def test_multiple_parts_are_joined():
    body = {"candidates": [{"content": {"parts": [{"text": "Part one. "}, {"text": "Part two."}]}}]}
    service = _service(lambda r: httpx.Response(200, json=body))
    assert service.generate(PROMPT) == "Part one. Part two."


def test_missing_key_raises_without_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_success_body())

    service = GeminiLLMService(api_key="", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMServiceError, match="GEMINI_API_KEY"):
        service.generate(PROMPT)
    assert calls == []


def test_rate_limit_raises_clear_message():
    service = _service(lambda r: httpx.Response(429, json={"error": {"code": 429}}))
    with pytest.raises(LLMRateLimitError) as exc:
        service.generate(PROMPT)
    assert "try again in a minute" in str(exc.value).lower()


def test_timeout_raises_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    service = _service(handler, timeout=1.0)
    with pytest.raises(LLMTimeoutError):
        service.generate(PROMPT)


def test_connect_timeout_raises_timeout_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timed out", request=request)

    with pytest.raises(LLMTimeoutError):
        _service(handler).generate(PROMPT)


def test_server_error_raises_service_error():
    service = _service(lambda r: httpx.Response(500, json={"error": {"code": 500}}))
    with pytest.raises(LLMServiceError, match="HTTP 500"):
        service.generate(PROMPT)


def test_blocked_response_raises_without_candidates():
    service = _service(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMServiceError, match="no answer"):
        service.generate(PROMPT)


def test_empty_answer_mentions_finish_reason():
    body = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
    service = _service(lambda r: httpx.Response(200, json=body))
    with pytest.raises(LLMServiceError, match="MAX_TOKENS"):
        service.generate(PROMPT)


def test_api_key_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    # A rate-limited call exercises the error path that logs.
    with pytest.raises(LLMRateLimitError):
        _service(lambda r: httpx.Response(429, json={})).generate(PROMPT)
    assert API_KEY not in caplog.text
