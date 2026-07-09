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

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import (
    connections_service, delegation_service, goals_service, memory_service,
    profile_service,
)
from app.services.llm import build_chat_client, chat_create, llm

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
        "name": "assign_task",
        "description": "Delegate a task to a CONNECTED person — 'ask Priya to send "
        "the deck', 'get Rahul to book the venue'. They must already be a connection.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string"},
            "to": {"type": "string", "description": "connection's name or email"},
            "when": {"type": "string", "description": "ISO 8601 datetime or empty"},
            "reason": {"type": "string", "description": "why it matters (optional)"},
        }, "required": ["title", "to"]}}},
    {"type": "function", "function": {
        "name": "list_delegated",
        "description": "List the tasks the user has assigned to other people and their "
        "status (use for 'what did I hand off', 'did Priya do X').",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "connect_person",
        "description": "Send a connection request to someone by email so they can be "
        "assigned tasks. Needs their email address.",
        "parameters": {"type": "object", "properties": {
            "email": {"type": "string"},
        }, "required": ["email"]}}},
    {"type": "function", "function": {
        "name": "set_goal",
        "description": "Save a longer-term GOAL / north-star the user names — e.g. "
        "'get fit', 'launch the app by Sept', 'read 12 books this year', 'save "
        "₹1L'. Goals are bigger than tasks; use this when they talk about what "
        "they're working toward (NOT a single dated to-do).",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "the goal, short"},
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


# Executors return a small structured result so the loop can tell — deterministically,
# not by reading the model's prose — whether a real write persisted (`effect`) or the
# action errored out (`ok=False`). This is what lets us guarantee the reply never
# claims success for something that didn't actually happen.
def _ok(msg: str, effect: str | None = None) -> dict:
    return {"ok": True, "msg": msg, "effect": effect}


def _info(msg: str) -> dict:
    """Ran fine but did NOT write (guard/clash/duplicate/no-match)."""
    return {"ok": True, "msg": msg, "effect": None}


def _fail(msg: str) -> dict:
    return {"ok": False, "msg": msg, "effect": None}


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


async def _create_task(db, user, now, args) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return _fail("No title given.")
    prio = args.get("priority")
    prio = prio if isinstance(prio, int) and 1 <= prio <= 4 else 3
    # Duplicate guard: with one continuous conversation, the model must NEVER
    # silently re-create something already on the list. This does a semantic
    # (embedding) lookup — but a flaky embeddings endpoint must NEVER block a
    # real task creation, so treat any failure here as "no duplicate found".
    if not args.get("force"):
        try:
            probe = f"{title}. {args.get('reason') or ''}".strip()
            dupes = await memory_service.find_duplicates(
                db, llm, user_id=user.id, text=probe)
            for mem, _sim in dupes:
                existing = await db.get(Task, mem.source_id) if mem.source_id else None
                if existing is not None and existing.status != "completed":
                    return _info(
                        f'ALREADY EXISTS: "{existing.title}" is already on the list — '
                        "do NOT create a duplicate. Tell the user it's already there. "
                        "Only if they clearly want a separate second one, call "
                        "create_task again with force=true.")
        except Exception:
            logging.warning("duplicate check skipped (embedding unavailable)",
                            exc_info=True)
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
            return _info(
                f'CONFLICT: the user already has "{clash.title}" at '
                f"{_fmt_local(clash.deadline, user, '%H:%M')}. Tell them about "
                "this clash and ask if they still want both; only if they "
                "confirm, call create_task again with force=true.")
    # ── Durable write FIRST: commit the task before anything that can fail, so a
    # later embedding hiccup can never lose it. This is the row the user sees. ──
    task = Task(user_id=user.id, title=title, reason=args.get("reason") or None,
                priority=prio, importance="high" if prio == 1 else "medium",
                deadline=when)
    db.add(task)
    await db.flush()
    db.add(TaskHistory(task_id=task.id, event="created"))
    await db.commit()
    # Best-effort semantic memory (for search/dedup) — the task is already saved,
    # so if embedding fails we just log and move on.
    try:
        mem = await memory_service.remember(
            db, llm, user_id=user.id, kind="task",
            content=f"{title}. {args.get('reason') or ''}".strip(),
            source_type="task", source_id=task.id, commit=False)
        task.embedding_id = mem.id
        await db.commit()
    except Exception:
        await db.rollback()
        logging.warning("task embedding skipped (task already saved)", exc_info=True)
    if timed:
        note = " (that time today had passed, so I set the next day)" if rolled else ""
        return _ok(f'Added "{title}" for {_fmt_local(when, user)}.{note}', "created")
    return _ok(f'Created task "{title}".', "created")


async def _complete_task(db, user, now, args) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return _info("Which task?")
    row = await db.scalar(
        select(Task).where(Task.user_id == user.id, Task.status != "completed",
                           Task.title.ilike(f"%{title}%")).limit(1))
    if row is None:
        return _info(f'No open task matching "{title}" — nothing was changed. '
                     "Tell the user you couldn't find it; do not claim it's done.")
    row.status = "completed"
    row.progress = 100
    row.completed_at = datetime.now(timezone.utc)
    # Add history via the FK directly — appending to row.history would trigger an
    # illegal async lazy-load (history wasn't eager-loaded on this query).
    db.add(TaskHistory(task_id=row.id, event="completed"))
    delegation_service.notify_completed(db, row, user)  # ping the delegator if assigned
    await db.commit()
    return _ok(f'Marked "{row.title}" done.', "completed")


async def _assign_task(db, user, now, args) -> dict:
    title = (args.get("title") or "").strip()
    to = (args.get("to") or "").strip()
    if not title or not to:
        return _info("Need a task and who to assign it to.")
    target = None
    if "@" in to:
        target = await connections_service.get_user_by_email(db, to)
    if target is None:
        conns = await connections_service.connected_users(db, user.id)
        matches = [u for u in conns if to.lower() in u.display_name.lower()]
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            return _info("Which one? You're connected with "
                         + ", ".join(u.display_name for u in matches))
    if target is None:
        return _info(
            f"NOT ASSIGNED: you're not connected with “{to}”, so nothing was sent. "
            "Tell the user plainly it did NOT go through and offer to send a "
            "connection request if they give the email. Do not claim it's assigned.")
    try:
        task = await delegation_service.assign(
            db, user, target, title=title, reason=args.get("reason"),
            deadline=_parse_dt(args.get("when"), now),
            priority=args.get("priority") or 3)
    except HTTPException as e:
        return _info(f"NOT ASSIGNED: {e.detail} Tell the user it didn't go through.")
    return _ok(f'Assigned “{task.title}” to {target.display_name}.', "assigned")


async def _list_delegated(db, user, now, args) -> dict:
    rows = list(await db.scalars(
        select(Task).where(Task.assigned_by_id == user.id,
                           Task.status != "completed")))
    if not rows:
        return _info("You haven't delegated anything that's still open.")
    ids = {t.user_id for t in rows}
    names = {u.id: u.display_name
             for u in await db.scalars(select(User).where(User.id.in_(ids)))}
    return _info("You've delegated: " + "; ".join(
        f'“{t.title}” → {names.get(t.user_id, "?")} ({t.status})' for t in rows))


async def _connect_person(db, user, now, args) -> dict:
    email = (args.get("email") or "").strip()
    if "@" not in email:
        return _info("I need their email address to send a connection request.")
    try:
        r = await connections_service.request(db, user, email)
    except HTTPException as e:
        return _info(str(e.detail))
    return _ok(r.get("message", "Request sent."))


async def _set_goal(db, user, now, args) -> dict:
    title = (args.get("title") or "").strip()
    if not title:
        return _info("What's the goal?")
    existing = await goals_service.active_titles(db, user.id)
    if any(title.lower() in t.lower() or t.lower() in title.lower()
           for t in existing):
        return _info(f'"{title}" is already one of your goals.')
    g = await goals_service.add(db, user.id, title)
    return _ok(f'Locked in a new goal: "{g.title}". 🎯 I\'ll keep it in mind.', "goal")


async def _remember_fact(db, user, now, args) -> dict:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return _info("Nothing to remember.")
    # Best-effort: the fact is nice-to-have, so a flaky embedding shouldn't error.
    try:
        await memory_service.remember(
            db, llm, user_id=user.id, kind="preference", content=fact,
            source_type="preference", commit=True)
    except Exception:
        await db.rollback()
        logging.warning("remember_fact embedding failed", exc_info=True)
        return _info("(Noted, though I couldn't file it away permanently just now.)")
    return _ok(f"Got it — I'll remember that: {fact}", "remembered")


_EXECUTORS = {
    "create_task": _create_task,
    "complete_task": _complete_task,
    "assign_task": _assign_task,
    "list_delegated": _list_delegated,
    "connect_person": _connect_person,
    "set_goal": _set_goal,
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
    about = await profile_service.get_about(db, user.id)
    goals = await goals_service.active_titles(db, user.id)
    goal_lines = "; ".join(goals) if goals else ""

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
        + ("LANGUAGE (most important): the user chose HINDI. ALWAYS reply in natural "
           "Hindi/Hinglish (Devanagari or roman script, whatever reads naturally), "
           "EVEN IF they type in English. Never reply in plain English.\n"
           if user.language == "hi" else
           "LANGUAGE (most important): reply in the EXACT language of the user's latest "
           "message. Default to English, but Hinglish in -> Hinglish out; Hindi -> "
           "Hindi. Never switch to English when they wrote Hindi/Hinglish.\n")
        +
        "EVERYTHING IS A TASK: a to-do and a meeting/call/appointment are both just "
        "tasks. Use create_task for all of them — put a specific time in `when` for "
        "anything that happens at a set time, leave it empty for an open to-do. If "
        "the user gives NO time, DON'T ask for one — just create the open to-do.\n"
        "DELEGATION: to hand a task to someone else ('ask Priya to…', 'get Rahul "
        "to…'), use assign_task — they must be a connection. connect_person(email) "
        "sends a connection request; list_delegated shows what you've handed off.\n"
        "REASON like a PA: use the Current state and recent conversation to be "
        "genuinely useful — connect a new request to their existing tasks, flag "
        "clashes, tight timing, or prep needed, and check in on the status of "
        "pending things when relevant. Only ask a clarifying question when you "
        "genuinely can't act (a time is NOT required); otherwise just act.\n"
        "INTENT FIRST (critical): before doing anything, read the LATEST message "
        "and classify it — (a) a clear NEW instruction to add/schedule/complete "
        "something, (b) an answer to your own last question (e.g. 'yes', 'done', "
        "'2pm'), (c) a question or comment, or (d) small talk. Use the tools ONLY "
        "for (a), or for (b) when they confirm something is finished. For (c) and "
        "(d), just reply in words — do NOT call any tool, do NOT create/complete "
        "anything, and do NOT bring up duplicates or conflicts. NEVER infer a task "
        "from older messages; the latest message alone decides if you act. When "
        "genuinely unsure, ask ONE short clarifying question instead of acting.\n"
        "ACT (only when intent is a clear instruction): call the tool and confirm "
        "it's DONE — don't ask 'would you like me to…'. When they say they finished/"
        "did/completed something, call complete_task. A task with a time IS its own "
        "reminder. If create_task reports a CONFLICT or ALREADY EXISTS, tell them "
        "plainly and ask before adding another. If a time already passed today, use "
        "the next day. Older messages and the task list are context only — never "
        "re-create or re-complete something just because it appears earlier.\n"
        "HONESTY (critical): NEVER say something was created, added, assigned, or "
        "marked done unless you actually CALLED that tool THIS turn AND its result "
        "confirmed success. If you didn't call the tool, nothing happened — so don't "
        "claim it did. If a tool result says NOT ASSIGNED, ALREADY EXISTS, CONFLICT, "
        "no match, or an error, relay that honestly and do NOT report success. It is "
        "far better to say 'that didn't go through' than to falsely say '✅ done'.\n"
        "GOALS & MEANING: the user has bigger goals (below). When a new task ties to "
        "a goal, name the connection briefly ('nice — that's straight at your "
        "fitness goal 💪'). When they name a fresh ambition, call set_goal. Once in a "
        "while — not every message — ask a light 'why' to understand what matters "
        "('what's pushing this deadline?'), and genuinely celebrate wins when they "
        "finish something that mattered (a quick 🙌, not a paragraph).\n"
        "STYLE: keep replies short (1-3 sentences) and warm — sprinkle in a fitting "
        "emoji or two (✅ 📅 🔔 🙌 etc.), but don't overdo it. When you need to ask "
        "for missing details or offer choices, present them as short bullet points "
        "(each on its own line starting with •), not one long run-on question. Use "
        "their name rarely. When "
        "the user reveals a lasting preference or fact about themselves, call "
        "remember_fact. Use what you know about them to be more personal. Never "
        f"invent facts. Now: {now.isoformat()} (year {now.year}; never a past year).\n\n"
        + (f"What I know about {user.display_name}:\n{profile}\n\n" if profile else "")
        + (f"In their own words (they wrote this about themselves — trust it):\n"
           f"{about}\n\n" if about else "")
        + (f"Their goals: {goal_lines}\n\n" if goal_lines else "")
        + f"Current state —\nTasks: {task_lines}\n\n"
        f"Relevant memory:\n{context}"
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history[-20:])
    messages.append({"role": "user", "content": message})

    # Ground truth of what actually happened this turn — used to make the reply
    # honest regardless of what the model tries to say.
    ledger: list[dict] = []

    async def _finalize(reply: str) -> dict:
        """Guarantee the reply doesn't claim success for anything that errored out.
        If any tool crashed, re-ask the model with an explicit failure note so it
        tells the user plainly; fall back to a deterministic warning."""
        failed = [l for l in ledger if not l["ok"]]
        if failed:
            names = ", ".join(sorted({l["tool"].replace("_", " ") for l in failed}))
            messages.append({"role": "system", "content": (
                f"IMPORTANT: these actions ERRORED and were NOT saved: {names}. "
                "You MUST tell the user, in their language, that these did not go "
                "through and to try again — do NOT say done/created/assigned for "
                "them. Keep it short and warm.")})
            try:
                r2 = await chat_create(client, model, messages=messages)
                fixed = (r2.choices[0].message.content or "").strip()
                if fixed:
                    return {"reply": fixed, "actions": actions}
            except Exception:
                logging.exception("honesty re-ask failed")
            reply = ((reply + " ") if reply else "") + (
                "⚠️ Something went wrong on my end and that didn't save — please "
                "try once more.")
        return {"reply": reply, "actions": actions}

    for _ in range(4):  # allow a few tool round-trips
        resp = await chat_create(
            client, model, messages=messages, tools=TOOLS, tool_choice="auto")
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return await _finalize((msg.content or "").strip())
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
                out = await executor(db, user, now, args) if executor \
                    else _fail(f"Unknown tool {tc.function.name}.")
            except Exception as e:
                # Roll back so one failed tool can't poison later tools in the
                # same turn (the bug behind "said done but nothing saved").
                await db.rollback()
                logging.exception("agent tool %s failed", tc.function.name)
                out = _fail(f"Couldn't complete {tc.function.name} ({type(e).__name__}).")
            ledger.append({"tool": tc.function.name, "ok": out["ok"],
                           "effect": out.get("effect")})
            actions.append({"tool": tc.function.name, "args": args,
                            "result": out["msg"], "ok": out["ok"],
                            "effect": out.get("effect")})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": out["msg"]})

    # Ran out of tool rounds — ask the model to wrap up in plain text.
    resp = await chat_create(client, model, messages=messages)
    return await _finalize((resp.choices[0].message.content or "").strip())
