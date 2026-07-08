"""FCM device tokens — one per device per user, for native push."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixin import TimestampMixin, UUIDMixin


class FcmToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "fcm_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    token: Mapped[str] = mapped_column(String(400), unique=True, index=True, nullable=False)
