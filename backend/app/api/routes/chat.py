"""Conversational endpoint (retrieve-then-generate) and memory search.

The chat reply is grounded in the user's own memories: we embed the message,
pull the most relevant memories, and hand them to the model as context. If
nothing relevant is found, the model is told to say so and ask — never
hallucinate (PRD AI behaviour).
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.conversation import ConversationTurn
from app.models.task import Task
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    MemoryCitation,
    MemorySearchHit,
    MemorySearchRequest,
)
from app.services import agent, memory_service, profile_service
from app.services.llm import llm


async def _refresh_profile_bg(user_id) -> None:
    """Keep the learned profile fresh (gated to ~once/day) without blocking chat."""
    try:
        async with SessionLocal() as db:
            u = await db.get(User, user_id)
            if u:
                await profile_service.maybe_refresh(db, llm, u)
    except Exception:
        logging.exception("background profile refresh failed")

router = APIRouter(tags=["chat"])

def _system_prompt(assistant_name: str) -> str:
    return (
        f"You are {assistant_name}, a professional, friendly executive assistant "
        "(Artificial Assistant & Reconciliation To Human). Be concise, warm, and "
        "human — 1-3 short sentences, no bullet dumps, no jargon. Use the context "
        "below to ground your answer. If the context doesn't cover it, say so "
        "briefly and ask one short follow-up. Never invent facts. Never assume a "
        "task is done. Address the user by name when natural."
    )

# Only surface a memory as a "based on" reference when it's clearly relevant.
_CITE_MIN_SIMILARITY = 0.35

_GREETINGS = {"hi", "hey", "hello", "yo", "hola", "sup", "good morning",
              "good evening", "good afternoon"}


def _stub_reply(name: str, message: str, hits: list) -> str:
    """Human-sounding placeholder used until a chat provider (Azure/OpenAI) is
    configured. No prompt echo, no scores — just a friendly, useful message."""
    msg = message.strip().lower().rstrip("!?. ")
    top = hits[0][0].content if hits else None
    note = " (My conversational AI isn't switched on yet, so this is a simple reply.)"
    if msg in _GREETINGS:
        return (f"Hi {name}! How can I help — want to review today's tasks, add "
                f"something new, or search what you've told me before?" + note)
    if top:
        return (f"Here's what's most relevant to that: “{top.split('.')[0]}”. "
                f"Want me to open it or add something new, {name}?" + note)
    return (f"I don't have anything on that yet, {name}. Tell me a bit more and "
            f"I'll remember it." + note)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    hits = await memory_service.search(
        db, llm, user_id=user.id, query=payload.message, limit=8
    )
    # Drop memories whose task is already completed — a done task shouldn't linger
    # in "based on what you've told me" or be fed to the agent as live context.
    task_src = [m.source_id for m, _ in hits if m.source_type == "task" and m.source_id]
    if task_src:
        done = set(await db.scalars(
            select(Task.id).where(Task.id.in_(task_src), Task.status == "completed")))
        if done:
            hits = [(m, s) for (m, s) in hits
                    if not (m.source_type == "task" and m.source_id in done)]

    actions: list = []
    if settings.resolved_provider == "stub":
        reply = _stub_reply(user.display_name, payload.message, hits)
    else:
        context = ("\n".join(f"- ({mem.kind}) {mem.content}" for mem, _ in hits)
                   if hits else "(no relevant memories found)")
        # Recent conversation so multi-turn dialogue stays coherent.
        history_rows = list(await db.scalars(
            select(ConversationTurn).where(ConversationTurn.user_id == user.id)
            .order_by(ConversationTurn.created_at.desc()).limit(20)))
        history = [{"role": t.role, "content": t.content} for t in reversed(history_rows)]
        try:
            result = await agent.run(db, user, payload.message, history, context)
            reply = result["reply"]
            actions = result["actions"]
        except Exception:
            # Never 500 on an upstream AI error — degrade to a calm message.
            logging.exception("chat agent failed")
            reply = ("I'm having trouble reaching my AI brain right now. "
                     "Your tasks and reminders still work — try me again in a moment.")

    # Persist both turns; recent turns feed short-term context, later summarized.
    # Never let a DB hiccup 500 the chat — the reply is already computed.
    try:
        db.add_all([
            ConversationTurn(user_id=user.id, role="user", content=payload.message),
            ConversationTurn(user_id=user.id, role="assistant", content=reply),
        ])
        await db.commit()
    except Exception:
        logging.exception("failed to persist conversation turns")
        await db.rollback()

    # Keep raw conversation bounded: summarize + prune old turns when they pile up.
    try:
        await memory_service.prune_conversation(db, llm, user_id=user.id)
    except Exception:
        pass

    # Learn from this interaction — refresh the profile in the background (~1/day).
    if settings.resolved_provider != "stub":
        background_tasks.add_task(_refresh_profile_bg, user.id)

    # Citations only for real answers, and only clearly-relevant memories.
    citations = []
    if settings.resolved_provider != "stub":
        citations = [
            MemoryCitation(
                id=mem.id, kind=mem.kind, content=mem.content, similarity=round(sim, 3)
            )
            for mem, sim in hits if sim >= _CITE_MIN_SIMILARITY
        ]
    return ChatResponse(reply=reply, citations=citations, actions=actions)


@router.get("/chat/history")
async def chat_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent conversation, oldest first — so the chat survives a refresh."""
    rows = list(await db.scalars(
        select(ConversationTurn).where(ConversationTurn.user_id == user.id)
        .order_by(ConversationTurn.created_at.desc()).limit(50)))
    return [{"role": t.role, "content": t.content} for t in reversed(rows)]


@router.delete("/chat/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Start a fresh conversation — clears prior turns so old context stops
    bleeding into new requests. Tasks/meetings/memories are untouched."""
    await db.execute(
        delete(ConversationTurn).where(ConversationTurn.user_id == user.id))
    await db.commit()


@router.post("/memory/search", response_model=list[MemorySearchHit])
async def memory_search(
    payload: MemorySearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MemorySearchHit]:
    hits = await memory_service.search(
        db, llm, user_id=user.id, query=payload.query,
        kind=payload.kind, limit=payload.limit,
    )
    return [
        MemorySearchHit(
            id=mem.id, kind=mem.kind, content=mem.content,
            similarity=round(sim, 3), created_at=mem.created_at,
        )
        for mem, sim in hits
    ]
