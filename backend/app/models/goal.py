"""Goals — the user's high-level north stars. Tasks and follow-ups reference
them so AARTH understands WHY things matter, not just what's on the list."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class Goal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # active | done
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
