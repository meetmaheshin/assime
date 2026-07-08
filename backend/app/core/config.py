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
    azure_openai_endpoint: str = ""  # classic: https://<resource>.openai.azure.com/
    azure_openai_api_version: str = "2024-10-21"
    # New Azure AI Foundry v1 (OpenAI-compatible) base, e.g.
    # https://<resource>.services.ai.azure.com/openai/v1 — when set, we use the
    # standard OpenAI client (needed for gpt-5 family). Takes precedence.
    azure_openai_base_url: str = ""
    azure_deployment_reasoning: str = ""  # e.g. gpt-4.1-nano
    azure_deployment_cheap: str = ""      # falls back to reasoning if unset
    azure_deployment_embed: str = ""      # e.g. a text-embedding-3-small deployment

    # --- Embeddings (chosen independently from chat) ---
    # auto | local | openai | azure | stub.
    #   auto  = follow the chat provider (azure/openai) if it can embed, else stub
    #   local = on-device sentence-transformers (no API cost)
    embedding_provider: str = "auto"
    # fastembed (ONNX) model id; all-MiniLM-L6-v2 is 384-dim.
    local_embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"

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
    def azure_v1_base(self) -> str:
        """The v1 (OpenAI-compatible) base URL, if configured — either explicitly
        via AZURE_OPENAI_BASE_URL, or by pointing AZURE_OPENAI_ENDPOINT at a v1
        URL (…services.ai.azure.com/openai/v1). Empty = use the classic client.
        Auto-detecting the endpoint too means a misplaced v1 URL still works."""
        candidates = [self.azure_openai_base_url, self.azure_openai_endpoint]
        for raw in candidates:
            ep = (raw or "").rstrip("/")
            if not ep:
                continue
            # Users often paste the Foundry '…/openai/v1/responses' sample URL, or a
            # '…/chat/completions' one. The OpenAI-compatible base is '…/openai/v1'
            # (the SDK appends the surface itself), so strip those suffixes.
            for suffix in ("/responses", "/chat/completions", "/embeddings"):
                if ep.endswith(suffix):
                    ep = ep[: -len(suffix)].rstrip("/")
            if ep.endswith("/openai/v1"):
                return ep
            if "services.ai.azure.com" in ep:
                return ep if "/openai/v1" in ep else ep + "/openai/v1"
        return ""

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
    cartesia_tts_model: str = "sonic-3"  # sonic-2/sonic/-english were sunsetted
    cartesia_stt_model: str = "ink-whisper"
    cartesia_stt_language: str = ""  # "" = auto-detect (supports Hindi + English)

    # --- Deepgram (STT — better Hindi/Hinglish than Whisper) ---
    deepgram_api_key: str = ""
    # nova-3 is required for real multilingual code-switching (Hinglish); nova-2
    # + multi only transcribes English and drops the Hindi.
    deepgram_model: str = "nova-3"
    deepgram_language: str = "multi"  # code-switching: Hindi + English
    # auto = Deepgram if a key is set, else Cartesia
    stt_provider: str = "auto"

    @property
    def resolved_stt_provider(self) -> str:
        if self.stt_provider != "auto":
            return self.stt_provider
        return "deepgram" if self.deepgram_api_key else "cartesia"

    @property
    def resolved_deepgram_model(self) -> str:
        """nova-2 can't do multilingual Hindi (it drops it) — upgrade to nova-3
        whenever code-switching (`multi`) is requested. Guards against a stale
        DEEPGRAM_MODEL=nova-2 lingering in the deployment env."""
        if self.deepgram_language == "multi" and self.deepgram_model == "nova-2":
            return "nova-3"
        return self.deepgram_model

    @property
    def resolved_tts_model(self) -> str:
        """Cartesia sunsetted sonic-2/sonic/sonic-english — map any of them (or a
        stale env value) to the current sonic-3 so TTS never silently fails."""
        sunset = {"sonic-2", "sonic", "sonic-english", "sonic-2-2025-03-07"}
        return "sonic-3" if self.cartesia_tts_model in sunset else self.cartesia_tts_model
    # Default voice: "Priya — Trusted Operator" (Indian-accent female).
    cartesia_voice_id: str = "f6141af3-5f94-418c-80ed-a45d450e7e2e"

    @property
    def voice_enabled(self) -> bool:
        return bool(self.cartesia_api_key)

    # --- Web Push (VAPID) ---
    vapid_public_key: str = ""
    vapid_private_key_b64: str = ""  # base64 of the PKCS8 PEM private key
    vapid_subject: str = "mailto:admin@aath.app"

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key_b64)

    # Cost guardrail
    daily_token_budget: int = 200_000

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def async_database_url(self) -> str:
        """Ensure the asyncpg driver is used. Managed hosts (Railway/Render)
        hand out `postgresql://...`; SQLAlchemy async needs `postgresql+asyncpg://`."""
        u = self.database_url
        for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
            if u.startswith(prefix):
                return "postgresql+asyncpg://" + u[len(prefix):]
        return u


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
