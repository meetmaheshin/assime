"""notifications.meeting_id (for meeting reminders)

Revision ID: 0006_notif_meeting
Revises: 0005_assistant_name
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_notif_meeting"
down_revision: Union[str, None] = "0005_assistant_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("notifications", sa.Column(
        "meeting_id", UUID,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_notifications_meeting_id", "notifications", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_meeting_id", table_name="notifications")
    op.drop_column("notifications", "meeting_id")
