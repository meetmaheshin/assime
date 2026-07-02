"""Conversational endpoint (retrieve-then-generate) and memory search.

The chat reply is grounded in the user's own memories: we embed the message,
pull the most relevant memories, and hand them to the model as context. If
nothing relevant is found, the model is told to say so and ask — never
hallucinate (PRD AI behaviour).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
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

_SYSTEM = (
    "You are A.A.T.H (Artificial Assistant To Human), a professional, friendly "
    "executive assistant. Be concise, "
    "motivating, no fluff. Answer ONLY from the context below. If the context "
    "does not contain the answer, say you don't have it yet and ask a short "
    "follow-up question. Never invent facts. Never assume a task is done."
)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    hits = await memory_service.search(
        db, llm, user_id=user.id, query=payload.message, limit=8
    )

    if hits:
        context = "\n".join(f"- ({mem.kind}) {mem.content}" for mem, _ in hits)
    else:
        context = "(no relevant memories found)"

    prompt = f"Context (the user's memory):\n{context}\n\nUser: {payload.message}"
    reply = await llm.complete(_SYSTEM, prompt, reasoning=True)

    # Persist both turns; recent turns feed short-term context, later summarized.
    db.add_all([
        ConversationTurn(user_id=user.id, role="user", content=payload.message),
        ConversationTurn(user_id=user.id, role="assistant", content=reply),
    ])
    await db.commit()

    citations = [
        MemoryCitation(
            id=mem.id, kind=mem.kind, content=mem.content, similarity=round(sim, 3)
        )
        for mem, sim in hits
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
