"""
Gemini (Google AI Studio) implementation of the LLMService interface.

Uses the Gemini API `generateContent` REST endpoint with httpx.
Docs: https://ai.google.dev/gemini-api/docs
"""

import logging

import httpx

from app.core.config import settings
from app.services.llm_service import (
    LLMService,
    LLMServiceError,
    LLMTimeoutError,
    LLMRateLimitError,
)

logger = logging.getLogger(__name__)

# Current free-tier text model; override with LLM_MODEL.
DEFAULT_MODEL = "gemini-4-hydrogen"
API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT_SECONDS = 30.0


class GeminiLLMService(LLMService):

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.Client | None = None,
    ):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.LLM_MODEL or DEFAULT_MODEL
        self.timeout = timeout
        self._http_client = http_client

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        if not self._api_key:
            raise LLMServiceError(
                "Gemini is not configured: set GEMINI_API_KEY in your environment."
            )

        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        # The key travels only in this header — never in the URL, body, or logs.
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        url = f"{API_BASE_URL}/models/{self.model}:generateContent"

        try:
            response = self._post(url, headers, payload)
        except httpx.TimeoutException as exc:
            logger.warning("Gemini request timed out after %.0fs.", self.timeout)
            raise LLMTimeoutError() from exc
        except httpx.HTTPError as exc:
            logger.warning("Gemini request failed: %s", type(exc).__name__)
            raise LLMServiceError("Could not reach the AI service. Please try again.") from exc

        if response.status_code == 429:
            logger.warning("Gemini rate limit reached (HTTP 429).")
            raise LLMRateLimitError()

        if response.status_code >= 400:
            logger.error("Gemini API responded with HTTP %s.", response.status_code)
            raise LLMServiceError(
                f"The AI service returned an error (HTTP {response.status_code})."
            )

        return self._extract_text(response)

    def _post(self, url: str, headers: dict, payload: dict) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client.post(url, headers=headers, json=payload, timeout=self.timeout)
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, headers=headers, json=payload)

    @staticmethod
    def _extract_text(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMServiceError("The AI service returned an unreadable response.") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMServiceError(
                "The AI service returned no answer (it may have been blocked by safety filters)."
            )

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            reason = candidates[0].get("finishReason")
            suffix = f" ({reason})" if reason else ""
            raise LLMServiceError(f"The AI service returned an empty answer{suffix}.")

        return text
