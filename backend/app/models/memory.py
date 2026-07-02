"""Semantic memory — the differentiator.

Every meaningful item (task, note, decision, meeting summary, chat turn worth
remembering) is embedded and stored here. Retrieval filters by user_id + metadata
and ranks by vector distance. This is what powers memory search, duplicate
detection, and retrieve-then-generate.
"""
from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class Memory(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "memories"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # What kind of memory: task | project | note | meeting | decision | chat | person
    kind: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    # Optional back-reference to the structured row this memory summarizes.
    source_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )

    # The canonical text that was embedded (also shown when citing a memory).
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embed_dim), nullable=False
    )
    # 0-100 confidence in this memory's accuracy (never assume; ask if low).
    confidence: Mapped[int] = mapped_column(Integer, default=80, nullable=False)


# Approximate-nearest-neighbour index for fast cosine search. ivfflat needs the
# table populated before it's efficient; for MVP scale it's fine and Alembic
# creates it. Cosine distance matches how we normalize/query embeddings.
Index(
    "ix_memories_embedding_cosine",
    Memory.embedding,
    postgresql_using="ivfflat",
    postgresql_ops={"embedding": "vector_cosine_ops"},
    postgresql_with={"lists": 100},
)
