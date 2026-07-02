"""user.assistant_name

Revision ID: 0005_assistant_name
Revises: 0004_user_prefs
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_assistant_name"
down_revision: Union[str, None] = "0004_user_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("assistant_name", sa.String(60),
                                     server_default="AARTH", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "assistant_name")
