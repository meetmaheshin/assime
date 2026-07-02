import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    task_id: uuid.UUID | None
    status: str
    alert_level: str
    created_at: datetime


class RespondRequest(BaseModel):
    # For overdue accountability: blocked|forgot|too_busy|waiting|not_important|other
    reason_code: str | None = None
    # Free-text answer (e.g. evening review).
    text: str | None = Field(default=None, max_length=2000)


class RespondResult(BaseModel):
    message: str
    notification: NotificationOut
