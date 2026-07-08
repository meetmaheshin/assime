"""Goals — the user's north stars, referenced by the agent + nudges."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import Goal


async def list_for_user(db: AsyncSession, user_id) -> list[Goal]:
    return list(await db.scalars(
        select(Goal).where(Goal.user_id == user_id)
        .order_by(Goal.status, Goal.created_at.desc())))


async def active_titles(db: AsyncSession, user_id) -> list[str]:
    rows = await db.scalars(
        select(Goal.title).where(Goal.user_id == user_id, Goal.status == "active")
        .limit(6))
    return list(rows)


async def add(db: AsyncSession, user_id, title: str) -> Goal:
    g = Goal(user_id=user_id, title=title.strip()[:200], status="active")
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return g


async def set_status(db: AsyncSession, user_id, goal_id: uuid.UUID, status: str) -> None:
    g = await db.get(Goal, goal_id)
    if g and g.user_id == user_id:
        g.status = status
        await db.commit()


async def delete(db: AsyncSession, user_id, goal_id: uuid.UUID) -> None:
    g = await db.get(Goal, goal_id)
    if g and g.user_id == user_id:
        await db.delete(g)
        await db.commit()
