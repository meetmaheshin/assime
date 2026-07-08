"""users.handle (opt-in discoverability) + invite_code

Revision ID: 0013_handle_invite
Revises: 0012_delegation
Create Date: 2026-07-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_handle_invite"
down_revision: Union[str, None] = "0012_delegation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("handle", sa.String(24), nullable=True))
    op.add_column("users", sa.Column("invite_code", sa.String(16), nullable=True))
    op.create_index("ix_users_handle", "users", ["handle"], unique=True)
    op.create_index("ix_users_invite_code", "users", ["invite_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_invite_code", table_name="users")
    op.drop_index("ix_users_handle", table_name="users")
    op.drop_column("users", "invite_code")
    op.drop_column("users", "handle")
