import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    reason: str | None = None
    project_id: uuid.UUID | None = None
    importance: str = "medium"
    priority: int = Field(default=3, ge=1, le=5)
    deadline: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    # If the client already checked for duplicates and wants to force-create.
    skip_duplicate_check: bool = False


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    reason: str | None = None
    project_id: uuid.UUID | None = None
    importance: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    deadline: datetime | None = None
    tags: list[str] | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    reason: str | None
    project_id: uuid.UUID | None
    importance: str
    priority: int
    status: str
    progress: int
    deadline: datetime | None
    completed_at: datetime | None
    tags: list[str]
    ai_notes: str | None
    created_at: datetime
    updated_at: datetime


class DuplicateMatch(BaseModel):
    id: uuid.UUID
    title: str
    similarity: float
    status: str


class TaskCreateResult(BaseModel):
    """If duplicates are found and not skipped, task is null and the client asks
    the user: same / new / follow-up (per PRD duplicate detection)."""

    task: TaskOut | None
    possible_duplicates: list[DuplicateMatch] = Field(default_factory=list)


class OverdueReason(BaseModel):
    # blocked | forgot | too_busy | waiting | not_important | other
    reason_code: str
    detail: str | None = None
