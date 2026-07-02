"""Conversational endpoint (retrieve-then-generate) and memory search.

The chat reply is grounded in the user's own memories: we embed the message,
pull the most relevant memories, and hand them to the model as context. If
nothing relevant is found, the model is told to say so and ask — never
hallucinate (PRD AI behaviour).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.conversation import ConversationTurn
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    MemoryCitation,
    MemorySearchHit,
    MemorySearchRequest,
)
from app.services import memory_service
from app.services.llm import llm

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    hits = await memory_service.search(
        db, llm, user_id=user.id, query=payload.message, limit=8
    )

    if settings.resolved_provider == "stub":
        reply = _stub_reply(user.display_name, payload.message, hits)
    else:
        if hits:
            context = "\n".join(f"- ({mem.kind}) {mem.content}" for mem, _ in hits)
        else:
            context = "(no relevant memories found)"
        prompt = f"Context (the user's memory):\n{context}\n\nUser: {payload.message}"
        reply = await llm.complete(_system_prompt(user.assistant_name), prompt, reasoning=True)

    # Persist both turns; recent turns feed short-term context, later summarized.
    db.add_all([
        ConversationTurn(user_id=user.id, role="user", content=payload.message),
        ConversationTurn(user_id=user.id, role="assistant", content=reply),
    ])
    await db.commit()

    # Keep raw conversation bounded: summarize + prune old turns when they pile up.
    try:
        await memory_service.prune_conversation(db, llm, user_id=user.id)
    except Exception:
        pass

    # Citations only for real answers, and only clearly-relevant memories.
    citations = []
    if settings.resolved_provider != "stub":
        citations = [
            MemoryCitation(
                id=mem.id, kind=mem.kind, content=mem.content, similarity=round(sim, 3)
            )
            for mem, sim in hits if sim >= _CITE_MIN_SIMILARITY
        ]
    return ChatResponse(reply=reply, citations=citations)


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
