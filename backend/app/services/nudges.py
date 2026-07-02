"""The nudge engine — what makes AARTH feel like a real PA.

Scans a user's tasks and generates proactive follow-ups: morning briefing,
overdue accountability ("you planned to finish X — what happened?"), due-today
checks, and an evening review. Respects quiet hours and a daily cap so it never
spams. Idempotent per (kind, task, local-day).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.task import Task
from app.models.user import User

DAILY_CAP = 6  # never spam


def _local(now: datetime, tz: str) -> datetime:
    try:
        return now.astimezone(ZoneInfo(tz))
    except Exception:
        return now.astimezone(timezone.utc)


def _in_quiet_hours(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight (e.g. 22–7)


async def _exists_today(db, user_id, kind, task_id, day_start_utc) -> bool:
    stmt = select(Notification.id).where(
        Notification.user_id == user_id,
        Notification.kind == kind,
        Notification.created_at >= day_start_utc,
    )
    stmt = stmt.where(Notification.task_id == task_id) if task_id is not None \
        else stmt.where(Notification.task_id.is_(None))
    return (await db.scalar(stmt)) is not None


async def generate(
    db: AsyncSession, user: User, now: datetime | None = None, force: bool = False
) -> list[Notification]:
    now = now or datetime.now(timezone.utc)
    local = _local(now, user.timezone)
    hour = local.hour
    day_start_utc = local.replace(
        hour=0, minute=0, second=0, microsecond=0
    ).astimezone(timezone.utc)

    if not force and _in_quiet_hours(hour, user.quiet_hours_start, user.quiet_hours_end):
        return []  # don't disturb during quiet hours

    sent_today = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.created_at >= day_start_utc
        )
    ) or 0
    budget = max(0, DAILY_CAP - sent_today)
    if budget <= 0:
        return []

    open_tasks = list(await db.scalars(
        select(Task).where(Task.user_id == user.id, Task.status != "completed")
        .order_by(Task.priority)
    ))
    overdue = [t for t in open_tasks if t.deadline and t.deadline < now]
    overdue_ids = {t.id for t in overdue}
    due_today = [
        t for t in open_tasks
        if t.deadline and t.id not in overdue_ids
        and day_start_utc <= t.deadline < day_start_utc + timedelta(days=1)
    ]

    created: list[Notification] = []

    async def add(kind: str, title: str, body: str, task_id=None) -> None:
        nonlocal budget
        if budget <= 0:
            return
        if await _exists_today(db, user.id, kind, task_id, day_start_utc):
            return
        n = Notification(user_id=user.id, kind=kind, title=title, body=body,
                         task_id=task_id)
        db.add(n)
        created.append(n)
        budget -= 1

    # Priority: overdue accountability > due-today > brief/review.
    for t in overdue:
        await add("overdue", "Overdue check-in",
                  f"You planned to finish “{t.title}” by "
                  f"{t.deadline.date().isoformat()}. What happened?", t.id)
    for t in due_today:
        await add("due_today", "Due today",
                  f"“{t.title}” is due today. Still on track?", t.id)
    if force or 5 <= hour < 12:
        top = ", ".join(t.title for t in open_tasks[:3])
        await add("morning_brief", f"Good morning, {user.display_name}",
                  f"Today's priorities: {top}." if top
                  else "No tasks yet — what's the plan today?")
    if force or 17 <= hour < 23:
        await add("evening_review", "Evening review",
                  "What did you complete today? Anything to move to tomorrow?")

    if created:
        await db.commit()
        for n in created:
            await db.refresh(n)
    return created
