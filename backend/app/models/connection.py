"""Connections — the trust boundary for task delegation.

Only connected users can assign each other tasks. A connection is a mutual link:
one user requests, the other accepts. Within an accepted connection, assignments
auto-accept (see delegation_service).
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class Connection(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_connection_pair"),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    addressee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    # pending | accepted | blocked
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
