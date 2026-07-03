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
CREATE_GRACE = timedelta(hours=3)  # don't nag about a just-added task


def _has_clock_time(dt: datetime | None, tz: str) -> bool:
    """A task with a specific time-of-day (not midnight, in the user's zone) is a
    scheduled event and earns a call-style pre-alert, like a meeting used to.
    Deadlines come back from the DB in UTC, so localize before checking."""
    if dt is None:
        return False
    local = _local(dt, tz)
    return local.hour != 0 or local.minute != 0


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

    day_end_utc = day_start_utc + timedelta(days=1)
    open_tasks = list(await db.scalars(
        select(Task).where(Task.user_id == user.id, Task.status != "completed")
        .order_by(Task.priority)))
    # Tasks happening at a set time today earn meeting-style pre-alerts.
    timed_today = [t for t in open_tasks
                   if _has_clock_time(t.deadline, user.timezone)
                   and day_start_utc <= t.deadline < day_end_utc]
    timed_today.sort(key=lambda t: t.deadline)

    sent_today = await db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.created_at >= day_start_utc
        )
    ) or 0
    budget = max(0, DAILY_CAP - sent_today)
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

    # ── Timed-task reminders — time-critical, so they bypass quiet hours ──
    for t in timed_today:
        mins = (t.deadline - now).total_seconds() / 60.0
        if 3 <= mins <= 15:
            kind = "task_soon"
        elif -4 <= mins < 3:
            kind = "task_now"
        else:
            continue
        if budget <= 0:
            break
        already = await db.scalar(select(Notification.id).where(
            Notification.user_id == user.id, Notification.kind == kind,
            Notification.task_id == t.id))
        if already:
            continue
        whenstr = _local(t.deadline, user.timezone).strftime("%H:%M")
        body = (f"“{t.title}” is happening now ({whenstr})."
                if kind == "task_now"
                else f"“{t.title}” at {whenstr} — in {int(round(mins))} min.")
        n = Notification(user_id=user.id, kind=kind, title="Reminder",
                         body=body, alert_level="call", task_id=t.id)
        db.add(n)
        created.append(n)
        budget -= 1

    # ── Everything else respects quiet hours ──
    if budget > 0 and (force or not _in_quiet_hours(
            hour, user.quiet_hours_start, user.quiet_hours_end)):
        # A task whose time has passed always earns a status check-in — that's the
        # whole point of accountability, so no creation grace here.
        overdue = [t for t in open_tasks if t.deadline and t.deadline < now]
        overdue_ids = {t.id for t in overdue}
        # Grace only on the "due today, still on track?" heads-up: don't post it
        # for a task the user just added (a real PA gives it room).
        fresh = now - CREATE_GRACE
        due_today = [
            t for t in open_tasks
            if t.deadline and t.id not in overdue_ids
            and day_start_utc <= t.deadline < day_end_utc
            and t.created_at and t.created_at < fresh]

        for t in overdue:
            await add("overdue", "Overdue check-in",
                      f"You planned to finish “{t.title}” by "
                      f"{t.deadline.date().isoformat()}. What happened?", t.id, alert="call")
        for t in due_today:
            await add("due_today", "Due today",
                      f"“{t.title}” is due today. Still on track?", t.id,
                      alert="call" if t.priority == 1 else "normal")
        if force or (user.morning_hour <= hour < 12):
            if timed_today:
                sched = "Today's schedule: " + "; ".join(
                    f"{_local(t.deadline, user.timezone):%H:%M} {t.title}"
                    for t in timed_today) + "."
            else:
                sched = "Nothing scheduled at a set time today."
            top = ", ".join(t.title for t in open_tasks[:3])
            pend = f" Pending: {top}." if top else " Nothing pending — nice."
            await add("morning_brief", f"Good morning, {user.display_name}",
                      sched + pend + " Want to start with the top one?", alert="call")
        if force or (user.evening_hour <= hour < 23):
            await add("evening_review", "Evening review",
                      "What did you complete today? Anything to move to tomorrow?")

    if created:
        await db.commit()
        for n in created:
            await db.refresh(n)
    return created
