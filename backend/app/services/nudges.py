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

import logging

from app.models.notification import Notification
from app.models.task import Task
from app.models.user import User
from app.services.llm import llm

DAILY_CAP = 6  # never spam
CREATE_GRACE = timedelta(hours=3)  # don't nag about a just-added task
FOLLOWUP_GAP = timedelta(hours=1)  # wait this long after a timed task, then check in


async def _accountability_message(user: User, open_tasks, now: datetime, mode: str) -> str:
    """LLM-written, human, ASSERTIVE check-in about ALL pending items — references
    why they matter and pushes the user to finish. Falls back to a firm template
    if the model is unavailable. `mode` = "followup" | "evening"."""
    lines = []
    for t in open_tasks[:8]:
        why = f" — matters because: {t.reason}" if t.reason else ""
        if t.deadline and t.deadline < now:
            hrs = (now - t.deadline).total_seconds() / 3600
            status = f" [overdue ~{int(hrs)}h]" if hrs >= 1 else " [time just passed]"
        elif t.deadline:
            try:
                status = f" [due {t.deadline.astimezone(ZoneInfo(user.timezone)):%H:%M}]"
            except Exception:
                status = ""
        else:
            status = ""
        lines.append(f'- "{t.title}"{why}{status}')
    tasklist = "\n".join(lines)
    when = "It's the end of the day." if mode == "evening" else f"It's {now:%A}, mid-day."
    system = (
        f"You are {user.assistant_name}, {user.display_name}'s accountability "
        "partner — NOT a soft, polite assistant. You are personally on the hook "
        "for making sure their tasks actually get DONE. Write ONE short check-in "
        "(2-4 sentences, like a sharp friend texting) that: asks where they are on "
        "their pending items, reminds them WHY the important ones matter (use the "
        "reasons given), and pushes them to finish. Be direct and a little firm — "
        "it's fine to call out something that's slipping. No bullet lists, no "
        "emojis, no corporate tone. Sound like a real person who genuinely wants "
        "them to succeed and won't let them off the hook."
    )
    prompt = (f"{when} {user.display_name}'s still-open items:\n{tasklist}\n\n"
              "Write the check-in message now (plain text, no lists).")
    try:
        msg = (await llm.complete(system, prompt, reasoning=False)).strip()
        if msg:
            return msg
    except Exception:
        logging.exception("accountability message generation failed")
    titles = ", ".join(f'"{t.title}"' for t in open_tasks[:4])
    return (f"Still open: {titles}. Where are you on these? Let's not let them "
            "slide — tell me what's done and what's actually blocking the rest.")


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

    # ── One ping AT the task time — time-critical, so it bypasses quiet hours.
    # No "10 min before" pre-alert: we're a PA, not a to-do app. Accountability
    # comes from the follow-up an hour later (below), not from nagging early. ──
    for t in timed_today:
        mins = (t.deadline - now).total_seconds() / 60.0
        if not (-3 <= mins <= 3):
            continue
        if budget <= 0:
            break
        already = await db.scalar(select(Notification.id).where(
            Notification.user_id == user.id, Notification.kind == "task_now",
            Notification.task_id == t.id))
        if already:
            continue
        whenstr = _local(t.deadline, user.timezone).strftime("%H:%M")
        n = Notification(user_id=user.id, kind="task_now", title="Reminder",
                         body=f"“{t.title}” — it's time ({whenstr}).",
                         alert_level="call", task_id=t.id)
        db.add(n)
        created.append(n)
        budget -= 1

    # ── Everything else respects quiet hours ──
    if budget > 0 and (force or not _in_quiet_hours(
            hour, user.quiet_hours_start, user.quiet_hours_end)):
        # Collective accountability follow-up: once a timed task's time has passed
        # (by ~an hour), check in on EVERYTHING still pending — one human, assertive
        # message that references why things matter and pushes back. Deduped to at
        # most once per ~3h so it never spams.
        passed_gap = any((now - t.deadline) >= FOLLOWUP_GAP for t in timed_today)
        if budget > 0 and open_tasks and passed_gap:
            recent = await db.scalar(select(Notification.id).where(
                Notification.user_id == user.id, Notification.kind == "followup",
                Notification.created_at >= now - timedelta(hours=3)))
            if not recent:
                msg = await _accountability_message(user, open_tasks, now, "followup")
                n = Notification(user_id=user.id, kind="followup",
                                 title="Checking in", body=msg, alert_level="call")
                db.add(n)
                created.append(n)
                budget -= 1

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
        if (force or (user.evening_hour <= hour < 23)) and budget > 0 \
                and not await _exists_today(
                    db, user.id, "evening_review", None, day_start_utc):
            if open_tasks:
                body = await _accountability_message(user, open_tasks, now, "evening")
            else:
                body = ("Day's done and nothing's left open — solid work. Want to "
                        "line anything up for tomorrow?")
            await add("evening_review", "Evening review", body, alert="call")

    if created:
        await db.commit()
        for n in created:
            await db.refresh(n)
    return created
