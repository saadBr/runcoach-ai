"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings for PaceCraft AI."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="RUNCOACH_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "PaceCraft AI"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "postgresql+psycopg://runcoach:runcoach-local@localhost:5432/runcoach"
    private_data_dir: Path = Path("data/private")
    athlete_id: UUID | None = None
    llm_provider: Literal["disabled", "openai"] = "disabled"
    openai_model: str | None = None
    openai_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance per application process."""

    return Settings()
