"""Daily planning / morning briefing.

Deterministic (no LLM): sorts by priority then deadline. Per the PRD, simple
planning shouldn't burn AI tokens — reasoning is reserved for /chat.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskOut

router = APIRouter(tags=["planning"])


@router.get("/today")
async def today(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = datetime.now(timezone.utc)
    open_tasks = list(
        await db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.status != "completed")
            .order_by(Task.priority, Task.deadline.nulls_last())
        )
    )
    overdue = [t for t in open_tasks if t.deadline and t.deadline < now]
    hour = now.hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    return {
        "greeting": f"Good {part}, {user.display_name}.",
        "priorities": [TaskOut.model_validate(t) for t in open_tasks[:3]],
        "overdue": [TaskOut.model_validate(t) for t in overdue],
        "open_count": len(open_tasks),
    }
