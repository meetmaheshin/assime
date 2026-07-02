"""user prefs: morning_hour, evening_hour, ring_enabled

Revision ID: 0004_user_prefs
Revises: 0003_meetings_alerts
Create Date: 2026-07-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_prefs"
down_revision: Union[str, None] = "0003_meetings_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("morning_hour", sa.Integer,
                                     server_default="8", nullable=False))
    op.add_column("users", sa.Column("evening_hour", sa.Integer,
                                     server_default="18", nullable=False))
    op.add_column("users", sa.Column("ring_enabled", sa.Boolean,
                                     server_default=sa.true(), nullable=False))


def downgrade() -> None:
    op.drop_column("users", "ring_enabled")
    op.drop_column("users", "evening_hour")
    op.drop_column("users", "morning_hour")
