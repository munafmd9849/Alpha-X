"""Application configuration."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    environment: str = "development"
    log_level: str = "info"
    max_file_size: int = 5_242_880  # 5MB
    rate_limit: int = 100
    allowed_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3002,https://alphafrontend-lilac.vercel.app"

    @property
    def origins_list(self) -> List[str]:
        """Get allowed origins as list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
