"""Application settings, loaded from environment / .env (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    env: str = "dev"
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440
    jwt_algorithm: str = "HS256"

    # Database / cache
    database_url: str = "postgresql+asyncpg://jarvis:jarvis@localhost:5432/jarvis"
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI — two-tier model strategy. Model ids are config, not code, so we can
    # swap GPT versions (or providers) without touching feature code.
    openai_api_key: str = ""
    openai_model_cheap: str = "gpt-4o-mini"
    openai_model_reasoning: str = "gpt-4o"
    openai_model_embed: str = "text-embedding-3-small"
    embed_dim: int = 1536

    # Cost guardrail
    daily_token_budget: int = 200_000

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
