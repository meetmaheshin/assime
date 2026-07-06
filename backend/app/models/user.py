"""User account. Multi-user from day one; every other row is scoped to a user."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # What the user calls their assistant (defaults to the product name).
    assistant_name: Mapped[str] = mapped_column(
        String(60), default="AARTH", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # UserSettings fields (kept inline for MVP; split to its own table later)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", nullable=False
    )
    quiet_hours_start: Mapped[int] = mapped_column(default=22, nullable=False)  # 0-23
    quiet_hours_end: Mapped[int] = mapped_column(default=7, nullable=False)  # 0-23
    morning_hour: Mapped[int] = mapped_column(default=8, nullable=False)  # briefing time
    evening_hour: Mapped[int] = mapped_column(default=20, nullable=False)  # review time (8pm)
    # When False, call-level nudges don't ring/vibrate (still show as a badge).
    ring_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Preferred language for chat + voice: "en" | "hi". Empty until they pick one.
    language: Mapped[str] = mapped_column(String(8), default="", nullable=False)

    projects: Mapped[list[Project]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
