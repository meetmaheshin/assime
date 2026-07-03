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

from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import memory_service, profile_service
from app.services.llm import build_chat_client, llm

TOOLS = [
    {"type": "function", "function": {
        "name": "create_task",
        "description": "Add a task for the user — a to-do OR a timed thing like a "
        "meeting, call, or appointment. For anything that happens at a set time, "
        "put that time in `when`.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "reason": {"type": "string", "description": "why it matters (optional)"},
            "priority": {"type": "integer", "description": "1 critical .. 4 low"},
            "when": {"type": "string", "description": "ISO 8601 datetime it's due or "
                     "happens at, or empty for an open to-do"},
            "force": {"type": "boolean", "description": "set true ONLY after the user "
                      "confirms adding despite a time clash with another task"},
        }, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "complete_task",
        "description": "Mark an existing task as done. Call this WHENEVER the user "
        "says they finished, did, completed, or are done with something.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "task title (fuzzy match ok)"},
        }, "required": ["title"]}}},
    {"type": "function", "function": {
        "name": "remember_fact",
        "description": "Save a durable fact or preference the user reveals about "
        "themselves — e.g. 'call me Mahesh', 'I work best in the mornings', 'my "
        "manager is Priya', 'don't remind me before 9am'. Use it whenever they "
        "share something worth remembering long-term (NOT for one-off tasks).",
        "parameters": {"type": "object", "properties": {
            "fact": {"type": "string", "description": "the fact/preference to remember"},
        }, "required": ["fact"]}}},
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


def _fmt_local(dt: datetime, user: User, fmt: str = "%a %H:%M") -> str:
    try:
        return dt.astimezone(ZoneInfo(user.timezone)).strftime(fmt)
    except Exception:
        return dt.strftime(fmt)


def _has_clock_time(dt: datetime | None) -> bool:
    """True if the datetime carries a specific time-of-day (not midnight) — the
    signal that a task is a scheduled event, so it earns a pre-alert + clash
    check. A date-only/open to-do just gets accountability nudges."""
    return dt is not None and (dt.hour != 0 or dt.minute != 0)


async def _create_task(db, user, now, args) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return "No title given."
    prio = args.get("priority")
    prio = prio if isinstance(prio, int) and 1 <= prio <= 4 else 3
    # `when` is the new name; accept `deadline`/`starts_at` for compatibility.
    when = _parse_dt(
        args.get("when") or args.get("deadline") or args.get("starts_at"), now)
    timed = _has_clock_time(when)
    rolled = False
    if timed and when < now:  # time already passed today -> assume next day
        when = when + timedelta(days=1)
        rolled = True
    # Clash check for timed tasks: warn instead of silently double-booking.
    if timed and not args.get("force"):
        window = timedelta(minutes=20)
        clash = await db.scalar(select(Task).where(
            Task.user_id == user.id, Task.status != "completed",
            Task.deadline.is_not(None),
            Task.deadline >= when - window,
            Task.deadline <= when + window).limit(1))
        if clash is not None:
            return (f'CONFLICT: the user already has "{clash.title}" at '
                    f"{_fmt_local(clash.deadline, user, '%H:%M')}. Tell them about "
                    "this clash and ask if they still want both; only if they "
                    "confirm, call create_task again with force=true.")
    task = Task(user_id=user.id, title=title, reason=args.get("reason") or None,
                priority=prio, importance="high" if prio == 1 else "medium",
                deadline=when)
    task.history.append(TaskHistory(event="created"))
    db.add(task)
    await db.flush()
    mem = await memory_service.remember(
        db, llm, user_id=user.id, kind="task",
        content=f"{title}. {args.get('reason') or ''}".strip(),
        source_type="task", source_id=task.id, commit=False)
    task.embedding_id = mem.id
    await db.commit()
    if timed:
        note = " (that time today had passed, so I set the next day)" if rolled else ""
        return f'Added "{title}" for {_fmt_local(when, user)}.{note}'
    return f'Created task "{title}".'


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
    # Add history via the FK directly — appending to row.history would trigger an
    # illegal async lazy-load (history wasn't eager-loaded on this query).
    db.add(TaskHistory(task_id=row.id, event="completed"))
    await db.commit()
    return f'Marked "{row.title}" done.'


async def _remember_fact(db, user, now, args) -> str:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return "Nothing to remember."
    await memory_service.remember(
        db, llm, user_id=user.id, kind="preference", content=fact,
        source_type="preference", commit=True)
    return f"Got it — I'll remember that: {fact}"


_EXECUTORS = {
    "create_task": _create_task,
    "complete_task": _complete_task,
    "remember_fact": _remember_fact,
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
        .order_by(Task.priority).limit(10)))
    task_lines = "; ".join(
        f"P{t.priority} {t.title}" + (f" (at {_loc(t.deadline)})" if t.deadline else "")
        for t in tasks) or "none"
    profile = await profile_service.get_summary(db, user.id)

    system = (
        f"You are {user.assistant_name}, {user.display_name}'s executive assistant. "
        "Think and act like a sharp human PA, not a form-filler.\n"
        "SCOPE: your job is managing the user's tasks, reminders, schedule, and "
        "accountability. Greetings, small talk, and questions about YOU (what you "
        "can do, how to use you) are totally fine — answer warmly in one line. "
        "But you are NOT a general chatbot or search engine: if they ask for "
        "general knowledge or open-ended help — weather, news, sports, math, "
        "coding, translation, essays, recipes, 'tell me about X', facts, opinions "
        "— do NOT answer it and do NOT use tools. Give ONE short line that it's "
        "outside what you do and steer back to their tasks (e.g. \"That's not "
        "really my thing — I'm here for your tasks and reminders. Anything to add "
        "or check?\"). Never produce long or general-purpose content.\n"
        "LANGUAGE (most important): reply in the EXACT language of the user's latest "
        "message. Hinglish in -> Hinglish out; Hindi -> Hindi; English -> English. "
        "Never switch to English when they wrote Hindi/Hinglish.\n"
        "EVERYTHING IS A TASK: a to-do and a meeting/call/appointment are both just "
        "tasks. Use create_task for all of them — put a specific time in `when` for "
        "anything that happens at a set time, leave it empty for an open to-do. If "
        "the user gives NO time, DON'T ask for one — just create the open to-do.\n"
        "REASON like a PA: use the Current state and recent conversation to be "
        "genuinely useful — connect a new request to their existing tasks, flag "
        "clashes, tight timing, or prep needed, and check in on the status of "
        "pending things when relevant. Only ask a clarifying question when you "
        "genuinely can't act (a time is NOT required); otherwise just act.\n"
        "ACT: to add/schedule/complete something, call the tool and confirm it's "
        "DONE — don't ask 'would you like me to…'. When they say they finished/did/"
        "completed something, call complete_task. A task with a time IS its own "
        "reminder. If create_task reports a CONFLICT, tell them and ask before "
        "adding both. If a time already passed today, use the next day.\n"
        "Don't blindly repeat old titles/times from history, but DO use context to "
        "reason. Keep replies to 1-3 short sentences. Use their name rarely. When "
        "the user reveals a lasting preference or fact about themselves, call "
        "remember_fact. Use what you know about them to be more personal. Never "
        f"invent facts. Now: {now.isoformat()} (year {now.year}; never a past year).\n\n"
        + (f"What I know about {user.display_name}:\n{profile}\n\n" if profile else "")
        + f"Current state —\nTasks: {task_lines}\n\n"
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
