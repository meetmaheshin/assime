from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.task import DuplicateMatch, TaskOut


class CaptureDraft(BaseModel):
    title: str | None = None
    reason: str | None = None
    priority: int = 3
    deadline: datetime | None = None
    # Which field we last asked the user about: "title" | "reason" | None
    pending: str | None = None


class CaptureRequest(BaseModel):
    # May be empty on a "confirm create" call that only carries a ready draft.
    utterance: str = Field(default="", max_length=2000)
    draft: CaptureDraft | None = None
    skip_duplicate_check: bool = False


class CaptureResponse(BaseModel):
    # ask (needs more info) | created | duplicate
    action: str
    question: str | None = None
    draft: CaptureDraft
    task: TaskOut | None = None
    possible_duplicates: list[DuplicateMatch] = Field(default_factory=list)
