"""LLM + embedding access behind one interface.

The rest of the app depends on the `LLMClient` interface, never on a concrete
SDK. Chat and embeddings are resolved independently from config, so we can mix
providers — e.g. Azure OpenAI for chat + a local sentence-transformers model
for embeddings (real semantic search, zero API cost).
"""
from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from app.core.config import settings

# ─── Interface ────────────────────────────────────────────────
EmbedFn = Callable[[str], Coroutine[Any, Any, list[float]]]
CompleteFn = Callable[..., Coroutine[Any, Any, str]]


class LLMClient(ABC):
    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    async def complete(self, system: str, user: str, *, reasoning: bool = True) -> str: ...


class CompositeLLM(LLMClient):
    """Delegates embed() and complete() to independently-chosen backends."""

    def __init__(self, embed_fn: EmbedFn, complete_fn: CompleteFn) -> None:
        self._embed_fn = embed_fn
        self._complete_fn = complete_fn

    async def embed(self, text: str) -> list[float]:
        return await self._embed_fn(text)

    async def complete(self, system: str, user: str, *, reasoning: bool = True) -> str:
        return await self._complete_fn(system, user, reasoning=reasoning)


# ─── Embedding backends ───────────────────────────────────────
def _hash_embed_sync(text: str) -> list[float]:
    """Deterministic local pseudo-embedding — structurally valid, NOT semantic.
    Fallback so the app runs before a real embedder is configured."""
    vec = [0.0] * settings.embed_dim
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    for i, byte in enumerate(digest):
        vec[i % settings.embed_dim] += (byte - 128) / 128.0
    return vec


async def _hash_embed(text: str) -> list[float]:
    return _hash_embed_sync(text)


# Lazily-loaded local ONNX model (fastembed). Loaded once, then reused. No torch.
_local_model = None


def _get_local_model():
    global _local_model
    if _local_model is None:
        from fastembed import TextEmbedding

        _local_model = TextEmbedding(model_name=settings.local_embed_model)
    return _local_model


async def _local_embed(text: str) -> list[float]:
    # fastembed is synchronous + CPU-bound; run off the event loop.
    def _run() -> list[float]:
        model = _get_local_model()
        vec = next(iter(model.embed([text])))
        return vec.tolist()

    return await asyncio.to_thread(_run)


def _openai_embedder(client: AsyncOpenAI, model: str) -> EmbedFn:
    async def _embed(text: str) -> list[float]:
        resp = await client.embeddings.create(model=model, input=text)
        return resp.data[0].embedding

    return _embed


# ─── Chat backends ────────────────────────────────────────────
def _azure_client() -> AsyncOpenAI:
    """Azure chat client. Uses the new v1 (OpenAI-compatible) base URL when set
    — required for the gpt-5 family — else the classic Azure OpenAI client."""
    if settings.azure_v1_base:
        return AsyncOpenAI(
            base_url=settings.azure_v1_base,
            api_key=settings.azure_openai_api_key,
        )
    return AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )


# If a configured deployment vanishes from Azure (expired/deleted), fall back to a
# known-good model so the app keeps working without a redeploy. Learned at runtime.
FALLBACK_MODEL = "gpt-4o-mini"
_dead_models: set[str] = set()


def _deployment_missing(err: Exception) -> bool:
    s = str(err)
    return (getattr(err, "status_code", None) == 404
            or "DeploymentNotFound" in s
            or "Could not find an existing deployment" in s)


async def chat_create(client: AsyncOpenAI, model: str, **kwargs):
    """client.chat.completions.create with automatic fallback if the deployment
    is gone (404 DeploymentNotFound)."""
    use = FALLBACK_MODEL if model in _dead_models else model
    try:
        return await client.chat.completions.create(model=use, **kwargs)
    except Exception as err:  # noqa: BLE001
        if use != FALLBACK_MODEL and _deployment_missing(err):
            _dead_models.add(model)
            return await client.chat.completions.create(model=FALLBACK_MODEL, **kwargs)
        raise


def _openai_completer(client: AsyncOpenAI, reasoning_model: str, cheap_model: str) -> CompleteFn:
    async def _complete(system: str, user: str, *, reasoning: bool = True) -> str:
        model = reasoning_model if reasoning else cheap_model
        # No temperature: gpt-5 reasoning models only accept the default (1).
        resp = await chat_create(
            client, model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return (resp.choices[0].message.content or "").strip()

    return _complete


async def _stub_complete(system: str, user: str, *, reasoning: bool = True) -> str:
    return f"[stub reply — no chat provider configured] You said: {user[:200]}"


# ─── Wiring ───────────────────────────────────────────────────
def _resolve_embed_fn() -> EmbedFn:
    provider = settings.resolved_embedding_provider
    if provider == "local":
        return _local_embed
    if provider == "openai":
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _openai_embedder(client, settings.openai_model_embed)
    if provider == "azure" and settings.azure_deployment_embed:
        client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        return _openai_embedder(client, settings.azure_deployment_embed)
    return _hash_embed


def _resolve_complete_fn() -> CompleteFn:
    provider = settings.resolved_provider
    if provider == "azure":
        client = _azure_client()
        cheap = settings.azure_deployment_cheap or settings.azure_deployment_reasoning
        return _openai_completer(client, settings.azure_deployment_reasoning, cheap)
    if provider == "openai":
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        return _openai_completer(
            client, settings.openai_model_reasoning, settings.openai_model_cheap
        )
    return _stub_complete


def build_chat_client():
    """Return (async client, model) for tool-calling chat, or (None, None) if the
    provider has no tool support (stub)."""
    provider = settings.resolved_provider
    if provider == "azure":
        return _azure_client(), settings.azure_deployment_reasoning
    if provider == "openai":
        return AsyncOpenAI(api_key=settings.openai_api_key), settings.openai_model_reasoning
    return None, None


def build_llm_client() -> LLMClient:
    return CompositeLLM(_resolve_embed_fn(), _resolve_complete_fn())


# Module-level singleton, imported where needed.
llm: LLMClient = build_llm_client()
