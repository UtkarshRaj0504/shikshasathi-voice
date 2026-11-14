"""
Application-wide settings loaded from environment variables.
"""

from pathlib import Path
from pydantic_settings import BaseSettings

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Central configuration — values come from .env or the OS environment."""

    # Application
    APP_ENV: str = "development"
    APP_DEBUG: bool = True
    APP_SECRET_KEY: str = "change-me-to-a-random-secret"

    # Database
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str = "shikshasaathi"
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: str = "changeme"
    DATABASE_URL: str = "sqlite:///./shikshasathi.db"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # Test database (used only by pytest)
    TEST_DATABASE_NAME: str = "shikshasaathi_test"

    @property
    def TEST_DATABASE_URL(self) -> str:
        return "sqlite:///:memory:"

    # Uploads
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 20

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Frontend
    VITE_API_BASE_URL: str = "http://localhost:8000"

    # Gnani API keys & AI providers
    STT_PROVIDER: str = "auto"
    TTS_PROVIDER: str = "auto"
    VOICE_CLONE_PROVIDER: str = "mock"  # mock (default) | gnani | auto (gnani when GNANI_API_KEY is set)
    GNANI_API_KEY: str = ""
    GNANI_PRISMA_ENDPOINT: str = "https://api.vachana.ai/stt/v3"
    GNANI_EVON_ENDPOINT: str = ""
    GNANI_TIMBRE_ENDPOINT: str = "https://api.vachana.ai/api/v1/tts/inference"
    GNANI_VOICE_CLONE_ENDPOINT: str = "https://api.vachana.ai/api/v1/tts/voice-clone/embeddings"
    GNANI_TTS_MODEL: str = "timbre-v3.0"
    GNANI_TTS_VOICE: str = "Lakshmi"

    # Voice cloning limits (teacher voice profiles)
    VOICE_CLONE_MAX_PROFILES: int = 3  # max profiles a teacher may keep
    VOICE_CLONE_CREATE_RATE_LIMIT: int = 5  # create calls allowed per window
    VOICE_CLONE_PREVIEW_RATE_LIMIT: int = 10  # preview calls allowed per window
    VOICE_CLONE_RATE_WINDOW_SECONDS: int = 600  # rate-limit window (seconds)

    # Embedding & RAG
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    LLM_PROVIDER: str = "mock"
    LLM_MODEL: str = "gemini-3.5-flash-lite"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    SIMILARITY_THRESHOLD: float = 0.10  # Lenient retrieval floor (cross-lingual scores are lower); never decides refusal alone
    RAG_DEBUG: bool = False  # Set to true to show debug info in retrieval

    model_config = {
        "env_file": [str(BACKEND_DIR / ".env"), str(REPO_ROOT / ".env"), ".env"],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
