"""users.language (chat + voice preference)

Revision ID: 0011_user_language
Revises: 0010_user_profile
Create Date: 2026-07-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_user_language"
down_revision: Union[str, None] = "0010_user_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "language", sa.String(8), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "language")
