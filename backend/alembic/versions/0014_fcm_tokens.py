"""fcm_tokens table

Revision ID: 0014_fcm_tokens
Revises: 0013_handle_invite
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_fcm_tokens"
down_revision: Union[str, None] = "0013_handle_invite"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "fcm_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(400), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fcm_tokens_user_id", "fcm_tokens", ["user_id"])
    op.create_index("ix_fcm_tokens_token", "fcm_tokens", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_fcm_tokens_token", table_name="fcm_tokens")
    op.drop_index("ix_fcm_tokens_user_id", table_name="fcm_tokens")
    op.drop_table("fcm_tokens")
