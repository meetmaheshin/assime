"""LLM access behind a single interface.

The rest of the app never imports the OpenAI SDK directly — it depends on
`LLMClient`. That keeps model choice (and the provider itself) swappable from
config, and lets tests inject a fake.

Two-tier strategy (see .env.example):
  - cheap model     -> intent parsing, classification, tagging
  - reasoning model -> planning, coaching, chat, reviews
  - embed model     -> semantic memory
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from openai import AsyncOpenAI

from app.core.config import settings


class LLMClient(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    async def complete(
        self, system: str, user: str, *, reasoning: bool = True
    ) -> str: ...


class OpenAIClient(LLMClient):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def embed(self, text: str) -> list[float]:
        resp = await self._client.embeddings.create(
            model=settings.openai_model_embed,
            input=text,
        )
        return resp.data[0].embedding

    async def complete(self, system: str, user: str, *, reasoning: bool = True) -> str:
        model = (
            settings.openai_model_reasoning
            if reasoning
            else settings.openai_model_cheap
        )
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
        )
        return (resp.choices[0].message.content or "").strip()


class EchoClient(LLMClient):
    """Offline fallback used when no OPENAI_API_KEY is set. Lets the API boot and
    the non-AI paths (auth, CRUD, reminders) work without a key. AI answers are
    clearly stubbed so nobody mistakes them for real output.
    """

    async def embed(self, text: str) -> list[float]:
        # Deterministic pseudo-embedding so semantic tables still function in dev.
        import hashlib

        vec = [0.0] * settings.embed_dim
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        for i, byte in enumerate(digest):
            vec[i % settings.embed_dim] += (byte - 128) / 128.0
        return vec

    async def complete(self, system: str, user: str, *, reasoning: bool = True) -> str:
        return (
            "[stub reply — set OPENAI_API_KEY to enable real AI] "
            f"You said: {user[:200]}"
        )


def build_llm_client() -> LLMClient:
    if settings.openai_api_key and settings.openai_api_key.startswith("sk-"):
        return OpenAIClient()
    return EchoClient()


# Module-level singleton, imported where needed.
llm: LLMClient = build_llm_client()
