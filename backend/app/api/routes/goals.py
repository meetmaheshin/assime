"""Goals — the user's north stars."""
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import goals_service

router = APIRouter(prefix="/goals", tags=["goals"])


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("")
async def list_goals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return [{"id": str(g.id), "title": g.title, "status": g.status}
            for g in await goals_service.list_for_user(db, user.id)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_goal(
    payload: GoalIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    g = await goals_service.add(db, user.id, payload.title)
    return {"id": str(g.id), "title": g.title, "status": g.status}


@router.post("/{goal_id}/done")
async def complete_goal(
    goal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await goals_service.set_status(db, user.id, goal_id, "done")
    return {"ok": True}


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await goals_service.delete(db, user.id, goal_id)
