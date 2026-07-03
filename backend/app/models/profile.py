"""Per-user learned profile — the evolving 'what I know about you'.

Lives server-side, tied to the account (not the device), so it survives
reinstalls and follows the user across devices. This accumulated understanding
is the product's moat: the longer someone uses AARTH, the better it knows them.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class UserProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    # Concise, LLM-maintained narrative the assistant reads before every reply.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the summary was last regenerated (gate refreshes to ~once/day).
    refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
