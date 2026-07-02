"""Task and its history. Fields mirror the PRD §Task Fields.

Dependencies (belongs-to / depends-on / blocks) are modeled as a self-referential
many-to-many edge table so queries like "what blocks the launch?" are graph walks.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User

# Edge table: task_dependencies(dependent_id depends on dependency_id).
# dependent blocks nothing on its own; "blocks" is just the reverse direction.
task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column(
        "dependent_id",
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dependency_id",
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Task(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tasks"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The "why" — captured conversationally, central to the PRD philosophy.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    importance: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)  # 1=top

    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 0-100

    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    ai_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link back to the memory chunk embedded for this task (duplicate detection).
    embedding_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="tasks")
    project: Mapped[Project | None] = relationship(back_populates="tasks")
    history: Mapped[list[TaskHistory]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )

    # Tasks this task depends on (must be done first). Self-referential
    # many-to-many; string join conditions resolve after mapper configuration.
    depends_on: Mapped[list[Task]] = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin="Task.id == task_dependencies.c.dependent_id",
        secondaryjoin="Task.id == task_dependencies.c.dependency_id",
        backref="blocks",
    )


class TaskHistory(Base, UUIDMixin, TimestampMixin):
    """Append-only log of changes for accountability and reviews."""

    __tablename__ = "task_history"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # e.g. created, status_changed, deadline_moved, overdue_reason
    event: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # overdue reason enum: blocked|forgot|too_busy|waiting|not_important|other
    reason_code: Mapped[str | None] = mapped_column(String(24), nullable=True)

    task: Mapped[Task] = relationship(back_populates="history")
