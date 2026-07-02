"""Semantic memory: write-path (embed + store) and read-path (search).

This is the retrieve-before-generate engine. Structured rows live in their own
tables; here we keep the embedded canonical text so we can answer "what happened
with X?", detect duplicates, and ground chat replies in real history.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def find_duplicates(
    db: AsyncSession,
    llm: LLMClient,
    *,
    user_id: uuid.UUID,
    text: str,
    threshold: float = 0.82,
    limit: int = 5,
) -> list[tuple[Memory, float]]:
    """Task-kind memories similar enough to `text` to warrant a same/new/follow-up
    prompt (PRD duplicate detection). Never blindly duplicate work."""
    hits = await search(db, llm, user_id=user_id, query=text, kind="task", limit=limit)
    return [(m, sim) for m, sim in hits if sim >= threshold]
