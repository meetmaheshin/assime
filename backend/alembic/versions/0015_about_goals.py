"""user_profiles.about + goals table

Revision ID: 0015_about_goals
Revises: 0014_fcm_tokens
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_about_goals"
down_revision: Union[str, None] = "0014_fcm_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("about", sa.Text, nullable=True))
    op.create_table(
        "goals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
    op.drop_column("user_profiles", "about")
