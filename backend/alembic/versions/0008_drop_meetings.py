"""drop meetings table + notifications.meeting_id (everything is a task now)

Revision ID: 0008_drop_meetings
Revises: 0007_push
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_drop_meetings"
down_revision: Union[str, None] = "0007_push"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # Drop the FK column first (it references meetings.id), then the table.
    op.drop_index("ix_notifications_meeting_id", table_name="notifications")
    op.drop_column("notifications", "meeting_id")
    op.drop_index("ix_meetings_starts_at", table_name="meetings")
    op.drop_index("ix_meetings_user_id", table_name="meetings")
    op.drop_table("meetings")


def downgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meetings_user_id", "meetings", ["user_id"])
    op.create_index("ix_meetings_starts_at", "meetings", ["starts_at"])
    op.add_column("notifications", sa.Column(
        "meeting_id", UUID,
        sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True))
    op.create_index("ix_notifications_meeting_id", "notifications", ["meeting_id"])
