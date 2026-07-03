"""Learns and maintains a concise, evolving profile of the user from their own
behavior — the 'what I know about you' the assistant reads before every reply.

Server-side and account-scoped, so it compounds over time and follows the user
across devices/reinstalls. Refreshes are gated to ~once a day to bound cost.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import UserProfile
from app.models.task import Task, TaskHistory
from app.models.user import User

REFRESH_EVERY = timedelta(hours=24)


async def get_or_create(db: AsyncSession, user_id) -> UserProfile:
    p = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    if p is None:
        p = UserProfile(user_id=user_id)
        db.add(p)
        await db.flush()
    return p


async def get_summary(db: AsyncSession, user_id) -> str:
    p = await db.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
    return (p.summary or "") if p else ""


def _local_hour(dt: datetime, tz: str) -> int:
    try:
        return dt.astimezone(ZoneInfo(tz)).hour
    except Exception:
        return dt.hour


async def _gather_signals(db: AsyncSession, user: User) -> str:
    now = datetime.now(timezone.utc)
    tasks = list(await db.scalars(
        select(Task).where(Task.user_id == user.id)
        .order_by(Task.created_at.desc()).limit(80)))
    if not tasks:
        return ""
    open_n = sum(1 for t in tasks if t.status != "completed")
    done = [t for t in tasks if t.status == "completed"]
    overdue = [t for t in tasks
               if t.status != "completed" and t.deadline and t.deadline < now]

    hist = list(await db.scalars(
        select(TaskHistory).join(Task, TaskHistory.task_id == Task.id)
        .where(Task.user_id == user.id)
        .order_by(TaskHistory.created_at.desc()).limit(150)))
    reasons = Counter(h.reason_code for h in hist if h.reason_code)
    done_hours = Counter(_local_hour(h.created_at, user.timezone)
                         for h in hist if h.event == "completed")
    active = ", ".join(f"{h}:00" for h, _ in done_hours.most_common(3)) or "unknown"
    top_reasons = ", ".join(f"{k} x{v}" for k, v in reasons.most_common(4)) or "none logged"
    recent = "; ".join(t.title + (f" — {t.reason}" if t.reason else "")
                       for t in tasks[:25])
    return (
        f"Name: {user.display_name}. Timezone: {user.timezone}.\n"
        f"Open tasks: {open_n}. Completed (recent): {len(done)}. "
        f"Currently overdue: {len(overdue)}.\n"
        f"Most active/completion hours: {active}.\n"
        f"Reasons things slip (from check-ins): {top_reasons}.\n"
        f"Recent tasks (title — why):\n{recent}"
    )


async def refresh(db: AsyncSession, llm, user: User) -> None:
    """Regenerate the profile summary from current behavior signals."""
    signals = await _gather_signals(db, user)
    p = await get_or_create(db, user.id)
    if not signals:
        p.refreshed_at = datetime.now(timezone.utc)
        await db.commit()
        return
    system = (
        "You maintain a concise working profile of a user for their personal "
        "assistant. From the behavior data, write 4-8 short factual lines (no "
        "headers, no bullet symbols, no fluff) capturing: their recurring "
        "priorities and themes, work/active patterns, what they tend to delay "
        "and why, preferred times/communication style, and any notable people or "
        "projects. Be specific and genuinely useful to an assistant that will "
        "read this before every reply. If data is thin, note only what's clear."
    )
    try:
        summary = (await llm.complete(system, signals, reasoning=False)).strip()
        if summary:
            p.summary = summary[:2000]
    except Exception:
        logging.exception("profile refresh failed for %s", user.id)
    p.refreshed_at = datetime.now(timezone.utc)
    await db.commit()


async def maybe_refresh(db: AsyncSession, llm, user: User) -> None:
    """Refresh if the profile has no summary yet, or is older than REFRESH_EVERY.
    (A fresh account has no tasks on its first message, so we must keep trying
    until there's enough behavior to summarize — not lock in an empty profile.)"""
    p = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    now = datetime.now(timezone.utc)
    if p and p.summary and p.refreshed_at and (now - p.refreshed_at) < REFRESH_EVERY:
        return
    await refresh(db, llm, user)
