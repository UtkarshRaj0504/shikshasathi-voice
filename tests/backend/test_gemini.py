"""
Tests for GeminiLLMService and LLM provider factory.
All tests use mocked responses — no real API calls are made.
"""

import logging
import pytest
from unittest.mock import MagicMock, patch
import httpx

from app.core.config import settings
from app.services.llm_service import (
    GeminiLLMService,
    GeminiRateLimitError,
    GeminiTimeoutError,
    MockLLMService,
    OpenAILLMService,
    get_llm_service,
)


@pytest.fixture
def fake_gemini_key():
    return "AIzaSyTestFakeKey1234567890abcdef"


def make_gemini_response(text: str, status_code: int = 200) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": text}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ]
    }
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_gemini_llm_service_success(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key, model_name="gemini-3.5-flash-lite")
    mock_response = make_gemini_response("Photosynthesis converts sunlight into sugar.")

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        answer = service.generate_answer("Explain photosynthesis")

        assert answer == "Photosynthesis converts sunlight into sugar."
        assert mock_post.called
        call_args, call_kwargs = mock_post.call_args

        # Verify URL
        assert "gemini-3.5-flash-lite:generateContent" in call_args[0]
        # Verify API key is passed in header, not in URL query string
        assert "?" not in call_args[0]
        assert call_kwargs["headers"]["x-goog-api-key"] == fake_gemini_key
        # Verify payload structure
        payload = call_kwargs["json"]
        assert payload["contents"][0]["parts"][0]["text"] == "Explain photosynthesis"
        assert "system_instruction" not in payload


def test_gemini_llm_service_with_system_prompt(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_response = make_gemini_response("Here is the answer for a beginner.")

    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        answer = service.generate_answer(
            prompt="What is light?",
            system_prompt="You are an encouraging tutor.",
        )
        assert answer == "Here is the answer for a beginner."
        payload = mock_post.call_args[1]["json"]
        assert payload["system_instruction"]["parts"][0]["text"] == "You are an encouraging tutor."
        assert payload["contents"][0]["parts"][0]["text"] == "What is light?"


def test_gemini_llm_service_configurable_model(fake_gemini_key, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODEL", "gemini-test-custom-model")
    service = GeminiLLMService(api_key=fake_gemini_key)

    mock_response = make_gemini_response("Custom model output.")
    with patch("httpx.Client.post", return_value=mock_response) as mock_post:
        service.generate_answer("Test prompt")
        url = mock_post.call_args[0][0]
        assert "gemini-test-custom-model:generateContent" in url


def test_gemini_llm_service_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    service = GeminiLLMService(api_key="")
    with pytest.raises(ValueError, match="Gemini API key is not configured"):
        service.generate_answer("Hello")


def test_gemini_llm_service_rate_limit_429(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Quota exceeded"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(GeminiRateLimitError) as exc_info:
            service.generate_answer("Trigger rate limit")

        assert "try again in a minute" in str(exc_info.value).lower()


def test_gemini_llm_service_rate_limit_http_status_error(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Too Many Requests"
    http_error = httpx.HTTPStatusError("429 Too Many Requests", request=MagicMock(), response=mock_resp)

    with patch("httpx.Client.post", side_effect=http_error):
        with pytest.raises(GeminiRateLimitError) as exc_info:
            service.generate_answer("Trigger rate limit via exception")

        assert "try again in a minute" in str(exc_info.value).lower()


def test_gemini_llm_service_timeout(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key, timeout=5.0)

    with patch("httpx.Client.post", side_effect=httpx.ReadTimeout("Read timed out")):
        with pytest.raises((GeminiTimeoutError, TimeoutError)) as exc_info:
            service.generate_answer("Prompt that times out")

        assert "timed out" in str(exc_info.value).lower()


def test_gemini_llm_service_empty_candidates(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"candidates": []}
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="no candidates"):
            service.generate_answer("Prompt")


def test_gemini_llm_service_blocked_response(fake_gemini_key):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [],
        "promptFeedback": {"blockReason": "SAFETY"}
    }
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="SAFETY"):
            service.generate_answer("Prompt")


def test_gemini_llm_service_never_logs_api_key(fake_gemini_key, caplog):
    service = GeminiLLMService(api_key=fake_gemini_key)
    mock_response = make_gemini_response("Educational answer")

    with caplog.at_level(logging.DEBUG):
        with patch("httpx.Client.post", return_value=mock_response):
            service.generate_answer("Test question")

    # Assert that the secret API key is NEVER logged anywhere
    for record in caplog.records:
        assert fake_gemini_key not in record.message


def test_get_llm_service_default_when_unset(monkeypatch):
    # When LLM_PROVIDER is unset or empty
    monkeypatch.setattr(settings, "LLM_PROVIDER", "")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    service = get_llm_service()
    assert isinstance(service, MockLLMService)


def test_get_llm_service_mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    service = get_llm_service()
    assert isinstance(service, MockLLMService)


def test_get_llm_service_gemini_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    service = get_llm_service()
    assert isinstance(service, GeminiLLMService)


def test_get_llm_service_openai_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    service = get_llm_service()
    assert isinstance(service, OpenAILLMService)
