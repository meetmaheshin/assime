"""Semantic memory: write-path (embed + store) and read-path (search).

This is the retrieve-before-generate engine. Structured rows live in their own
tables; here we keep the embedded canonical text so we can answer "what happened
with X?", detect duplicates, and ground chat replies in real history.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import ConversationTurn
from app.models.memory import Memory
from app.services.llm import LLMClient


async def remember(
    db: AsyncSession,
    llm: LLMClient,
    *,
    user_id: uuid.UUID,
    kind: str,
    content: str,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    confidence: int = 80,
    commit: bool = True,
) -> Memory:
    """Embed `content` and store it as a durable memory for this user."""
    embedding = await llm.embed(content)
    memory = Memory(
        user_id=user_id,
        kind=kind,
        content=content,
        embedding=embedding,
        source_type=source_type,
        source_id=source_id,
        project_id=project_id,
        confidence=confidence,
    )
    db.add(memory)
    if commit:
        await db.commit()
        await db.refresh(memory)
    else:
        await db.flush()
    return memory


async def search(
    db: AsyncSession,
    llm: LLMClient,
    *,
    user_id: uuid.UUID,
    query: str,
    kind: str | None = None,
    limit: int = 8,
) -> list[tuple[Memory, float]]:
    """Return (memory, similarity) pairs, most similar first. similarity is in
    [0, 1] where 1 is identical (1 - cosine_distance)."""
    query_vec = await llm.embed(query)
    distance = Memory.embedding.cosine_distance(query_vec)

    stmt = (
        select(Memory, distance.label("distance"))
        .where(Memory.user_id == user_id)
        .order_by(distance)
        .limit(limit)
    )
    if kind is not None:
        stmt = stmt.where(Memory.kind == kind)

    rows = (await db.execute(stmt)).all()
    return [(row[0], 1.0 - float(row[1])) for row in rows]


async def prune_conversation(
    db: AsyncSession,
    llm: LLMClient,
    *,
    user_id: uuid.UUID,
    keep: int = 40,
    batch: int = 20,
) -> bool:
    """Keep raw conversation bounded: once it grows past keep+batch, fold the
    oldest `batch` turns into a single durable summary memory and delete the
    raw rows. Semantic recall of old chats is preserved (as a summary) while
    storage stays small. Returns True if it pruned."""
    total = await db.scalar(
        select(func.count(ConversationTurn.id)).where(ConversationTurn.user_id == user_id)
    ) or 0
    if total <= keep + batch:
        return False

    oldest = list(await db.scalars(
        select(ConversationTurn).where(ConversationTurn.user_id == user_id)
        .order_by(ConversationTurn.created_at).limit(batch)
    ))
    if not oldest:
        return False

    transcript = "\n".join(f"{t.role}: {t.content}" for t in oldest)
    try:
        summary = await llm.complete(
            "Summarize the key facts, decisions, commitments, names, tasks and "
            "dates from this conversation excerpt in 2-4 sentences. Be specific.",
            transcript, reasoning=False,
        )
    except Exception:
        summary = ""
    if summary and not summary.startswith("[stub"):
        await remember(db, llm, user_id=user_id, kind="summary",
                       content=summary, confidence=70, commit=False)
    for t in oldest:
        await db.delete(t)
    await db.commit()
    return True


async def find_duplicates(
    db: AsyncSession,
    llm: LLMClient,
    *,
    user_id: uuid.UUID,
    text: str,
    threshold: float | None = None,
    limit: int = 5,
) -> list[tuple[Memory, float]]:
    """Task-kind memories similar enough to `text` to warrant a same/new/follow-up
    prompt (PRD duplicate detection). Never blindly duplicate work."""
    if threshold is None:
        threshold = settings.duplicate_threshold
    hits = await search(db, llm, user_id=user_id, query=text, kind="task", limit=limit)
    return [(m, sim) for m, sim in hits if sim >= threshold]
