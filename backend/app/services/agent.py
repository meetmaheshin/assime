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
        }, "required": ["title", "starts_at"]}}},
    {"type": "function", "function": {
        "name": "complete_task",
        "description": "Mark an existing task as done.",
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
    db.add(Meeting(user_id=user.id, title=title, starts_at=starts))
    await db.commit()
    try:
        when = starts.astimezone(ZoneInfo(user.timezone)).strftime("%a %d %b %H:%M")
    except Exception:
        when = starts.strftime("%a %d %b %H:%M")
    return f'Added meeting "{title}" at {when}.'


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

    system = (
        f"You are {user.assistant_name}, {user.display_name}'s executive assistant.\n"
        "LANGUAGE RULE (most important): ALWAYS reply in the exact same language the "
        "user's latest message uses. If they wrote in Hinglish (Romanized Hindi like "
        "'mujhe kal meeting set karni hai'), you MUST reply in Hinglish (e.g. 'Theek "
        "hai, kal ki meeting set kar di hai'). If Hindi, reply Hindi. If English, "
        "English. Never switch to English when the user wrote Hindi/Hinglish.\n"
        "Be warm and brief — 1-2 short sentences.\n"
        "ACT, don't ask: when the user wants something added, scheduled, set, "
        "reminded, or completed, call the tool immediately and confirm it's DONE. "
        "Do NOT ask 'would you like me to…' or ask for confirmation before acting. "
        "Only ask a question if a REQUIRED detail is genuinely missing (e.g. no "
        "time was given at all). Never repeat a question you already asked.\n"
        "A meeting or task that has a time already IS its reminder — never offer "
        "to set a separate reminder; just confirm it's scheduled and that you'll "
        "remind them.\n"
        f"Current local time: {now.isoformat()}; resolve relative times ('4am', "
        "'tomorrow') against it. Use the user's name rarely, not every message. "
        "Never invent facts.\n"
        "LANGUAGE: reply in the SAME language and style the user uses. If they "
        "write in Hindi or Hinglish (Romanized Hindi), reply in natural Hinglish; "
        "if English, reply in English. Mirror them.\n\n"
        f"Relevant memory:\n{context}"
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history[-10:])
    messages.append({"role": "user", "content": message})

    for _ in range(4):  # allow a few tool round-trips
        resp = await client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS,
            tool_choice="auto", temperature=0.3)
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
        model=model, messages=messages, temperature=0.3)
    return {"reply": (resp.choices[0].message.content or "").strip(), "actions": actions}
