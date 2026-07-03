"""evening_review default 18->20 (8pm)

Revision ID: 0009_evening_8pm
Revises: 0008_drop_meetings
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_evening_8pm"
down_revision: Union[str, None] = "0008_drop_meetings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "evening_hour",
                    existing_type=sa.Integer(), server_default="20")
    # Shift users still on the old 6pm default up to the new 8pm default.
    op.execute("UPDATE users SET evening_hour = 20 WHERE evening_hour = 18")


def downgrade() -> None:
    op.alter_column("users", "evening_hour",
                    existing_type=sa.Integer(), server_default="18")
    op.execute("UPDATE users SET evening_hour = 18 WHERE evening_hour = 20")
