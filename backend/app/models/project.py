"""Project — a container for tasks, notes, people, and an AI summary."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class Project(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "projects"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # low | medium | high — how much this project matters, used in daily planning
    importance: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="projects")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
