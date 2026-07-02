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

from app.models.meeting import Meeting
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

    # Today's meetings (for the morning briefing).
    day_end_utc = day_start_utc + timedelta(days=1)
    meetings = list(await db.scalars(
        select(Meeting).where(
            Meeting.user_id == user.id,
            Meeting.starts_at >= day_start_utc,
            Meeting.starts_at < day_end_utc,
        ).order_by(Meeting.starts_at)
    ))

    created: list[Notification] = []

    async def add(kind, title, body, task_id=None, alert="normal") -> None:
        nonlocal budget
        if budget <= 0:
            return
        if await _exists_today(db, user.id, kind, task_id, day_start_utc):
            return
        n = Notification(user_id=user.id, kind=kind, title=title, body=body,
                         task_id=task_id, alert_level=alert)
        db.add(n)
        created.append(n)
        budget -= 1

    # Priority: overdue accountability (call-level) > due-today > brief/review.
    for t in overdue:
        await add("overdue", "Overdue check-in",
                  f"You planned to finish “{t.title}” by "
                  f"{t.deadline.date().isoformat()}. What happened?", t.id, alert="call")
    for t in due_today:
        # Critical items ring like a call; the rest are silent badges.
        await add("due_today", "Due today",
                  f"“{t.title}” is due today. Still on track?", t.id,
                  alert="call" if t.priority == 1 else "normal")
    if force or (user.morning_hour <= hour < 12):
        if meetings:
            def _fmt(m):
                return f"{_local(m.starts_at, user.timezone):%H:%M} {m.title}"
            mtg = "Today's meetings: " + "; ".join(_fmt(m) for m in meetings) + "."
        else:
            mtg = "I don't see any meetings today — what's on your calendar?"
        top = ", ".join(t.title for t in open_tasks[:3])
        pend = f" Pending: {top}." if top else " Nothing pending — nice."
        await add("morning_brief", f"Good morning, {user.display_name}",
                  mtg + pend + " Want to start with the top one?", alert="call")
    if force or (user.evening_hour <= hour < 23):
        await add("evening_review", "Evening review",
                  "What did you complete today? Anything to move to tomorrow?")

    if created:
        await db.commit()
        for n in created:
            await db.refresh(n)
    return created
