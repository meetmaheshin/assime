"""Delegation API — assign tasks to connected users and track them."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskOut
from app.services import connections_service, delegation_service

router = APIRouter(tags=["delegation"])


class AssignRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    to_email: EmailStr
    when: datetime | None = None
    reason: str | None = None
    priority: int = Field(default=3, ge=1, le=4)


@router.post("/assignments", response_model=TaskOut,
             status_code=status.HTTP_201_CREATED)
async def create_assignment(
    payload: AssignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    assignee = await connections_service.get_user_by_email(db, payload.to_email)
    if assignee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No AARTH user with that email yet.")
    task = await delegation_service.assign(
        db, user, assignee, title=payload.title, reason=payload.reason,
        deadline=payload.when, priority=payload.priority)
    out = TaskOut.model_validate(task)
    out.assigned_by_name = user.display_name
    return out


@router.get("/delegated")
async def delegated_by_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Tasks I assigned to others, with the assignee + live status."""
    tasks = list(await db.scalars(
        select(Task).where(Task.assigned_by_id == user.id)
        .order_by(Task.created_at.desc())))
    names = {}
    ids = {t.user_id for t in tasks}
    if ids:
        names = {u.id: u.display_name
                 for u in await db.scalars(select(User).where(User.id.in_(ids)))}
    return [{
        "id": str(t.id), "title": t.title, "status": t.status,
        "deadline": t.deadline.isoformat() if t.deadline else None,
        "assignee_name": names.get(t.user_id, "someone"),
    } for t in tasks]


async def _load(db: AsyncSession, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return task


@router.post("/tasks/{task_id}/return")
async def return_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await delegation_service.return_task(db, user, await _load(db, task_id))
    return {"ok": True}


@router.post("/tasks/{task_id}/revoke")
async def revoke(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await delegation_service.revoke(db, user, await _load(db, task_id))
    return {"ok": True}
