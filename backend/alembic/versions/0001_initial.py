"""initial schema — users, projects, tasks, memories (pgvector), conversation

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # pgvector must exist before any Vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("timezone", sa.String(64), server_default="UTC", nullable=False),
        sa.Column("quiet_hours_start", sa.Integer, server_default="22", nullable=False),
        sa.Column("quiet_hours_end", sa.Integer, server_default="7", nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("importance", sa.String(16), server_default="medium", nullable=False),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("ai_summary", sa.Text, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    op.create_table(
        "tasks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", UUID,
                  sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("importance", sa.String(16), server_default="medium", nullable=False),
        sa.Column("priority", sa.Integer, server_default="3", nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer, server_default="0", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String),
                  server_default="{}", nullable=False),
        sa.Column("ai_notes", sa.Text, nullable=True),
        sa.Column("embedding_id", UUID, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])

    op.create_table(
        "task_history",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("task_id", UUID,
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.String(48), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("reason_code", sa.String(24), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_task_history_task_id", "task_history", ["task_id"])

    op.create_table(
        "task_dependencies",
        sa.Column("dependent_id", UUID,
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("dependency_id", UUID,
                  sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "memories",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=True),
        sa.Column("source_id", UUID, nullable=True),
        sa.Column("project_id", UUID, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(settings.embed_dim), nullable=False),
        sa.Column("confidence", sa.Integer, server_default="80", nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_kind", "memories", ["kind"])
    op.create_index("ix_memories_source_id", "memories", ["source_id"])
    op.create_index("ix_memories_project_id", "memories", ["project_id"])
    op.create_index(
        "ix_memories_embedding_cosine", "memories", ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )

    op.create_table(
        "conversation_turns",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_conversation_turns_user_id", "conversation_turns", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("conversation_turns")
    op.drop_index("ix_memories_embedding_cosine", table_name="memories")
    op.drop_table("memories")
    op.drop_table("task_dependencies")
    op.drop_table("task_history")
    op.drop_table("tasks")
    op.drop_table("projects")
    op.drop_table("users")
