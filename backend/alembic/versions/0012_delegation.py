"""connections table + task delegation fields

Revision ID: 0012_delegation
Revises: 0011_user_language
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_delegation"
down_revision: Union[str, None] = "0011_user_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("requester_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("addressee_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_connection_pair"),
    )
    op.create_index("ix_connections_requester_id", "connections", ["requester_id"])
    op.create_index("ix_connections_addressee_id", "connections", ["addressee_id"])

    op.add_column("tasks", sa.Column("assigned_by_id", UUID,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("tasks", sa.Column("assignment_status", sa.String(16),
                  server_default="none", nullable=False))
    op.add_column("tasks", sa.Column("assigned_at", sa.DateTime(timezone=True),
                  nullable=True))
    op.create_index("ix_tasks_assigned_by_id", "tasks", ["assigned_by_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_assigned_by_id", table_name="tasks")
    op.drop_column("tasks", "assigned_at")
    op.drop_column("tasks", "assignment_status")
    op.drop_column("tasks", "assigned_by_id")
    op.drop_index("ix_connections_addressee_id", table_name="connections")
    op.drop_index("ix_connections_requester_id", table_name="connections")
    op.drop_table("connections")
