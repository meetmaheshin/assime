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

    # LLM provider: auto | openai | azure | stub.
    # auto = azure if AZURE_OPENAI_ENDPOINT set, else openai if key looks real,
    #        else stub (offline). Model/deployment ids are config, not code, so
    #        we can swap versions or providers without touching feature code.
    llm_provider: str = "auto"

    # --- Standard OpenAI ---
    openai_api_key: str = ""
    openai_model_cheap: str = "gpt-4o-mini"
    openai_model_reasoning: str = "gpt-4o"
    openai_model_embed: str = "text-embedding-3-small"

    # --- Azure OpenAI (AI Foundry) ---
    # In Azure you call *deployment* names, not model names. Chat and embeddings
    # each need their own deployment in the Azure resource.
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""  # e.g. https://<resource>.openai.azure.com/
    azure_openai_api_version: str = "2024-10-21"
    azure_deployment_reasoning: str = ""  # e.g. gpt-4.1-nano
    azure_deployment_cheap: str = ""      # falls back to reasoning if unset
    azure_deployment_embed: str = ""      # e.g. a text-embedding-3-small deployment

    # --- Embeddings (chosen independently from chat) ---
    # auto | local | openai | azure | stub.
    #   auto  = follow the chat provider (azure/openai) if it can embed, else stub
    #   local = on-device sentence-transformers (no API cost)
    embedding_provider: str = "auto"
    local_embed_model: str = "all-MiniLM-L6-v2"  # 384-dim

    # Cosine-similarity threshold for duplicate-task detection. MiniLM scores
    # paraphrases lower than OpenAI embeddings, so this is tuned for the local
    # model; raise it toward ~0.8 if you switch to OpenAI/Azure embeddings.
    duplicate_threshold: float = 0.6

    embed_dim: int = 1536

    @property
    def resolved_embedding_provider(self) -> str:
        if self.embedding_provider != "auto":
            return self.embedding_provider
        if self.openai_api_key.startswith("sk-"):
            return "openai"
        if self.azure_openai_endpoint and self.azure_deployment_embed:
            return "azure"
        return "stub"

    @property
    def resolved_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.azure_openai_endpoint and self.azure_openai_api_key:
            return "azure"
        if self.openai_api_key.startswith("sk-"):
            return "openai"
        return "stub"

    # --- Cartesia (voice TTS + STT) ---
    cartesia_api_key: str = ""
    cartesia_version: str = "2024-11-13"
    cartesia_tts_model: str = "sonic-2"
    cartesia_stt_model: str = "ink-whisper"
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"

    @property
    def voice_enabled(self) -> bool:
        return bool(self.cartesia_api_key)

    # Cost guardrail
    daily_token_budget: int = 200_000

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
