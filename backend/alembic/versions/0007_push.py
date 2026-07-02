"""push_subscriptions + notifications.pushed

Revision ID: 0007_push
Revises: 0006_notif_meeting
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_push"
down_revision: Union[str, None] = "0006_notif_meeting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False, unique=True),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])
    op.add_column("notifications", sa.Column(
        "pushed", sa.Boolean, server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("notifications", "pushed")
    op.drop_table("push_subscriptions")
