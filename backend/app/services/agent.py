"""Conversational agent: chat that can actually DO things.

Unlike plain completion, this runs a tool-calling loop so AARTH can create
tasks/meetings, mark work done, and search memory straight from the chat — and
it's fed the recent conversation so multi-turn dialogue stays coherent.
Falls back cleanly when the provider has no tool support.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import memory_service
from app.services.llm import build_chat_client, llm

TOOLS = [
    {"type": "function", "function": {
        "name": "create_task",
        "description": "Add a to-do task for the user.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "reason": {"type": "string", "description": "why it matters (optional)"},
            "priority": {"type": "integer", "description": "1 critical .. 4 low"},
            "deadline": {"type": "string", "description": "ISO 8601 datetime or empty"},
        }, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "create_meeting",
        "description": "Put a meeting or event on the user's calendar.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "starts_at": {"type": "string", "description": "ISO 8601 datetime"},
            "force": {"type": "boolean", "description": "set true ONLY after the "
                      "user confirms adding despite a scheduling conflict"},
        }, "required": ["title", "starts_at"]}}},
    {"type": "function", "function": {
        "name": "complete_task",
        "description": "Mark an existing task as done. Call this WHENEVER the user "
        "says they finished, did, completed, or are done with something.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "task title (fuzzy match ok)"},
        }, "required": ["title"]}}},
]


def _parse_dt(s: str | None, now: datetime) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo or timezone.utc)
        # Small models sometimes emit a past year (e.g. 2023 from training data).
        # A scheduled item should never land years in the past — snap the year up.
        if dt.year < now.year:
            try:
                dt = dt.replace(year=now.year)
            except ValueError:  # Feb 29 edge
                dt = dt.replace(year=now.year, day=28)
        return dt
    except ValueError:
        return None


async def _create_task(db, user, now, args) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return "No title given."
    prio = args.get("priority")
    prio = prio if isinstance(prio, int) and 1 <= prio <= 4 else 3
    task = Task(user_id=user.id, title=title, reason=args.get("reason") or None,
                priority=prio, importance="high" if prio == 1 else "medium",
                deadline=_parse_dt(args.get("deadline"), now))
    task.history.append(TaskHistory(event="created"))
    db.add(task)
    await db.flush()
    mem = await memory_service.remember(
        db, llm, user_id=user.id, kind="task",
        content=f"{title}. {args.get('reason') or ''}".strip(),
        source_type="task", source_id=task.id, commit=False)
    task.embedding_id = mem.id
    await db.commit()
    return f'Created task "{title}".'


async def _create_meeting(db, user, now, args) -> str:
    title = (args.get("title") or "").strip()
    starts = _parse_dt(args.get("starts_at"), now)
    if not title or not starts:
        return "Need a title and a time."
    rolled = False
    if starts < now:  # requested time already passed today -> next day
        starts = starts + timedelta(days=1)
        rolled = True
    # Conflict check: warn instead of silently double-booking.
    if not args.get("force"):
        window = timedelta(minutes=20)
        clash = await db.scalar(select(Meeting).where(
            Meeting.user_id == user.id,
            Meeting.starts_at >= starts - window,
            Meeting.starts_at <= starts + window).limit(1))
        if clash is not None:
            try:
                cw = clash.starts_at.astimezone(ZoneInfo(user.timezone)).strftime("%H:%M")
            except Exception:
                cw = clash.starts_at.strftime("%H:%M")
            return (f'CONFLICT: the user already has "{clash.title}" at {cw}. Tell '
                    "them about this clash and ask if they still want both; only if "
                    "they confirm, call create_meeting again with force=true.")
    db.add(Meeting(user_id=user.id, title=title, starts_at=starts))
    await db.commit()
    try:
        when = starts.astimezone(ZoneInfo(user.timezone)).strftime("%a %d %b %H:%M")
    except Exception:
        when = starts.strftime("%a %d %b %H:%M")
    note = " (that time had passed today, so I scheduled the next day)" if rolled else ""
    return f'Added meeting "{title}" at {when}.{note}'


async def _complete_task(db, user, now, args) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return "Which task?"
    row = await db.scalar(
        select(Task).where(Task.user_id == user.id, Task.status != "completed",
                           Task.title.ilike(f"%{title}%")).limit(1))
    if row is None:
        return f'No open task matching "{title}".'
    row.status = "completed"
    row.progress = 100
    row.completed_at = datetime.now(timezone.utc)
    row.history.append(TaskHistory(event="completed"))
    await db.commit()
    return f'Marked "{row.title}" done.'


_EXECUTORS = {
    "create_task": _create_task,
    "create_meeting": _create_meeting,
    "complete_task": _complete_task,
}


async def run(
    db: AsyncSession, user: User, message: str, history: list[dict], context: str
) -> dict:
    """Tool-calling chat. `history` is prior turns [{role, content}]; `context`
    is retrieved memory. Returns {reply, actions} — actions is a debug trail of
    the tools invoked and their results."""
    actions: list[dict] = []
    client, model = build_chat_client()
    if client is None:  # no tool-capable provider
        reply = await llm.complete(
            f"You are {user.assistant_name}, a concise, warm executive assistant.",
            f"{context}\n\nUser: {message}", reasoning=True)
        return {"reply": reply, "actions": actions}

    try:
        now = datetime.now(timezone.utc).astimezone(ZoneInfo(user.timezone))
    except Exception:
        now = datetime.now(timezone.utc)

    # Give the agent the real picture so it can reason like a PA.
    def _loc(dt, fmt="%a %H:%M"):
        try:
            return dt.astimezone(ZoneInfo(user.timezone)).strftime(fmt)
        except Exception:
            return dt.strftime(fmt)

    tasks = list(await db.scalars(
        select(Task).where(Task.user_id == user.id, Task.status != "completed")
        .order_by(Task.priority).limit(8)))
    task_lines = "; ".join(
        f"P{t.priority} {t.title}" + (f" (due {_loc(t.deadline)})" if t.deadline else "")
        for t in tasks) or "none"
    upcoming = list(await db.scalars(
        select(Meeting).where(Meeting.user_id == user.id,
                              Meeting.starts_at >= now - timedelta(hours=1))
        .order_by(Meeting.starts_at).limit(6)))
    mtg_lines = "; ".join(f"{_loc(m.starts_at)} {m.title}" for m in upcoming) or "none"

    system = (
        f"You are {user.assistant_name}, {user.display_name}'s executive assistant. "
        "Think and act like a sharp human PA, not a form-filler.\n"
        "LANGUAGE (most important): reply in the EXACT language of the user's latest "
        "message. Hinglish in -> Hinglish out; Hindi -> Hindi; English -> English. "
        "Never switch to English when they wrote Hindi/Hinglish.\n"
        "REASON like a PA: use the Current state and recent conversation to be "
        "genuinely useful — connect a new request to their existing tasks/meetings, "
        "flag clashes, tight timing, or prep needed, and check in on the status of "
        "pending things when relevant. Ask ONE smart clarifying question when the "
        "request is ambiguous or missing a needed detail; otherwise just act.\n"
        "ACT: to add/schedule/complete something, call the tool and confirm it's "
        "DONE — don't ask 'would you like me to…'. When they say they finished/did/"
        "completed something, call complete_task. A timed meeting/task IS its own "
        "reminder. If create_meeting reports a CONFLICT, tell them and ask before "
        "adding both. If a time already passed today, use the next day.\n"
        "Don't blindly repeat old titles/times from history, but DO use context to "
        "reason. Keep replies to 1-3 short sentences. Use their name rarely. Never "
        f"invent facts. Now: {now.isoformat()} (year {now.year}; never a past year).\n\n"
        f"Current state —\nTasks: {task_lines}\nUpcoming meetings: {mtg_lines}\n\n"
        f"Relevant memory:\n{context}"
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": message})

    for _ in range(4):  # allow a few tool round-trips
        resp = await client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS,
            tool_choice="auto")
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"reply": (msg.content or "").strip(), "actions": actions}
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            } for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            executor = _EXECUTORS.get(tc.function.name)
            try:
                result = await executor(db, user, now, args) if executor \
                    else f"Unknown tool {tc.function.name}."
            except Exception as e:
                logging.exception("agent tool %s failed", tc.function.name)
                result = f"FAILED: {type(e).__name__}: {e}"
            actions.append({"tool": tc.function.name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # Ran out of tool rounds — ask the model to wrap up in plain text.
    resp = await client.chat.completions.create(
        model=model, messages=messages)
    return {"reply": (resp.choices[0].message.content or "").strip(), "actions": actions}
