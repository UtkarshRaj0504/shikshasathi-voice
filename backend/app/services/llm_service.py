"""
LLM service interface, provider errors, and the local mock implementation.
"""

import abc

from app.core.config import settings


class LLMServiceError(RuntimeError):
    """Base error for LLM provider failures."""


class LLMRateLimitError(LLMServiceError):
    """Provider rate limit hit — the caller should retry later."""

    def __init__(self, message: str = "The AI service is rate limited. Please try again in a minute."):
        super().__init__(message)


class LLMTimeoutError(LLMServiceError):
    """Provider took too long to answer."""

    def __init__(self, message: str = "The AI service timed out. Please try again."):
        super().__init__(message)


class LLMService(abc.ABC):

    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate a text answer for the given prompt."""
        pass


class MockLLMService(LLMService):
    """Offline stand-in used when no LLM provider is configured."""

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return (
            "This is a mock answer. Set LLM_PROVIDER=gemini and GEMINI_API_KEY "
            "to generate answers with a real model."
        )


def get_llm_service() -> LLMService:
    """Return the configured provider — MockLLMService when LLM_PROVIDER is unset."""
    provider = (settings.LLM_PROVIDER or "").strip().lower()

    if provider in ("", "mock"):
        return MockLLMService()

    if provider == "gemini":
        from app.services.gemini_llm_service import GeminiLLMService

        return GeminiLLMService()

    raise ValueError(
        f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. Supported values: mock, gemini."
    )
