"""
Application-wide settings loaded from environment variables.
"""

from pydantic_settings import BaseSettings


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

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    # JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # Test database (used only by pytest)
    TEST_DATABASE_NAME: str = "shikshasaathi_test"

    @property
    def TEST_DATABASE_URL(self) -> str:
        return (
            f"postgresql://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.TEST_DATABASE_NAME}"
        )

    # Uploads
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 20

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # Frontend
    VITE_API_BASE_URL: str = "http://localhost:8000"

    # Gnani API keys (populated in later phases)
    GNANI_API_KEY: str = ""
    GNANI_PRISMA_ENDPOINT: str = ""
    GNANI_EVON_ENDPOINT: str = ""
    GNANI_TIMBRE_ENDPOINT: str = ""
    GNANI_VOICE_CLONE_ENDPOINT: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
