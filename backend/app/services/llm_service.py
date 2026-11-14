"""
LLM service interface with Mock, OpenAI, and Gemini implementations,
plus a clearly marked TODO for Gnani Evon.
"""

import abc
import logging
import os
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService(abc.ABC):
    """Abstract base class for LLM services."""

    @abc.abstractmethod
    def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
        """Generate answer from prompt and system prompt."""
        pass


class MockLLMService(LLMService):
    """Mock LLM service for testing and development without live API calls."""

    def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
        return (
            "Based on the provided study materials, here is the answer: "
            "Photosynthesis is the process used by plants to convert light energy into chemical energy. "
            "Example: Green leaves use sunlight, water, and carbon dioxide to produce oxygen and energy in the form of sugar."
        )


class OpenAILLMService(LLMService):
    """Real OpenAI LLM implementation (used when LLM_PROVIDER=openai)."""

    def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
        api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OpenAI API key is not configured.")

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "temperature": 0.3
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]


class GeminiRateLimitError(RuntimeError):
    """Raised when Gemini API returns 429 Too Many Requests."""
    pass


class GeminiTimeoutError(TimeoutError):
    """Raised when Gemini API request times out."""
    pass


class GeminiLLMService(LLMService):
    """
    Gemini LLM service implementing LLMService interface using Google's
    official Generative Language REST API (v1beta generateContent).

    Uses a free-tier text model (configurable with LLM_MODEL, default: gemini-3.5-flash-lite).
    Reads the key from GEMINI_API_KEY without logging it.
    Handles 429 rate limits (with clear 'try again in a minute' guidance) and timeouts.
    """

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self._custom_model_name = model_name
        self._custom_api_key = api_key
        self.timeout = timeout

    @property
    def model_name(self) -> str:
        if self._custom_model_name:
            return self._custom_model_name
        return (
            getattr(settings, "LLM_MODEL", None)
            or os.getenv("LLM_MODEL")
            or "gemini-3.5-flash-lite"
        )

    def _get_api_key(self) -> str:
        key = (
            self._custom_api_key
            or getattr(settings, "GEMINI_API_KEY", None)
            or os.getenv("GEMINI_API_KEY")
        )
        if not key or not str(key).strip():
            raise ValueError(
                "Gemini API key is not configured. Please set GEMINI_API_KEY in your environment or .env file."
            )
        return str(key).strip()

    def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
        api_key = self._get_api_key()
        model = self.model_name

        # URL format per official Gemini REST API docs
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

        # Pass key via header strictly, never logging or leaking it
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        payload: dict = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
            },
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [
                    {"text": system_prompt}
                ]
            }

        logger.info(f"Calling Gemini API model: {model}")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)

                if response.status_code == 429:
                    logger.warning("Gemini API rate limit encountered (HTTP 429).")
                    raise GeminiRateLimitError(
                        "Gemini API rate limit exceeded (429). Please try again in a minute."
                    )

                response.raise_for_status()
                data = response.json()

        except httpx.TimeoutException as e:
            logger.warning(f"Gemini API request timed out after {self.timeout}s.")
            raise GeminiTimeoutError(
                f"Gemini API request timed out after {self.timeout}s. Please try again."
            ) from e

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Gemini API rate limit encountered (HTTP 429).")
                raise GeminiRateLimitError(
                    "Gemini API rate limit exceeded (429). Please try again in a minute."
                ) from e
            logger.error(f"Gemini API returned error status: {e.response.status_code}")
            raise RuntimeError(
                f"Gemini API error (HTTP {e.response.status_code}): {e.response.text}"
            ) from e

        except (GeminiRateLimitError, GeminiTimeoutError):
            raise

        except Exception as e:
            logger.error(f"Unexpected error communicating with Gemini API: {type(e).__name__}")
            raise RuntimeError(f"Failed to communicate with Gemini API: {e}") from e

        candidates = data.get("candidates", [])
        if not candidates:
            prompt_feedback = data.get("promptFeedback", {})
            block_reason = prompt_feedback.get("blockReason")
            if block_reason:
                raise RuntimeError(f"Gemini API blocked response: {block_reason}")
            raise RuntimeError("Gemini API returned no candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            finish_reason = candidates[0].get("finishReason")
            if finish_reason and finish_reason != "STOP":
                raise RuntimeError(f"Gemini generation stopped early: {finish_reason}")
            raise RuntimeError("Gemini API returned empty text in candidate content.")

        return text


# TODO: Gnani Evon LLM Implementation (Phase 6+)
# class GnaniEvonLLMService(LLMService):
#     """
#     Gnani Evon LLM API integration.
#     TODO: Implement once Gnani Evon endpoints and authentication documentation are confirmed.
#     Endpoint settings (not guessed): GNANI_EVON_ENDPOINT in config.py
#     """
#     def generate_answer(self, prompt: str, system_prompt: str = "") -> str:
#         raise NotImplementedError("Gnani Evon LLM integration pending official documentation.")


def get_llm_service() -> LLMService:
    """
    Factory function returning the configured LLM service.
    Defaults to MockLLMService if LLM_PROVIDER is unset, empty, or unknown.
    """
    provider = (getattr(settings, "LLM_PROVIDER", None) or os.getenv("LLM_PROVIDER") or "").strip().lower()
    if provider == "gemini":
        return GeminiLLMService()
    if provider == "openai":
        return OpenAILLMService()
    return MockLLMService()
