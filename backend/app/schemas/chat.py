import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MemoryCitation(BaseModel):
    id: uuid.UUID
    kind: str
    content: str
    similarity: float


class ChatResponse(BaseModel):
    reply: str
    # Memories the answer was grounded in (retrieve-then-generate transparency).
    citations: list[MemoryCitation] = Field(default_factory=list)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    kind: str | None = None
    limit: int = Field(default=8, ge=1, le=50)


class MemorySearchHit(BaseModel):
    id: uuid.UUID
    kind: str
    content: str
    similarity: float
    created_at: datetime
