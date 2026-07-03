"""Daily planning / morning briefing.

Deterministic (no LLM): sorts by priority then deadline. Per the PRD, simple
planning shouldn't burn AI tokens — reasoning is reserved for /chat.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
    try:
        local = now.astimezone(ZoneInfo(user.timezone))
    except Exception:
        local = now.astimezone(timezone.utc)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)

    open_tasks = list(
        await db.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.status != "completed")
            .order_by(Task.priority, Task.deadline.nulls_last())
        )
    )
    overdue = [t for t in open_tasks if t.deadline and t.deadline < now]
    # Tasks happening at a set time today (the old "meetings" view). Localize the
    # UTC deadline before deciding it has a specific time-of-day.
    def _timed(t: Task) -> bool:
        if not (t.deadline and day_start <= t.deadline < day_end):
            return False
        loc = t.deadline.astimezone(local.tzinfo)
        return bool(loc.hour or loc.minute)
    scheduled = sorted(
        (t for t in open_tasks if _timed(t)), key=lambda t: t.deadline)
    hour = local.hour
    part = "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    return {
        "greeting": f"Good {part}, {user.display_name}.",
        "priorities": [TaskOut.model_validate(t) for t in open_tasks[:3]],
        "overdue": [TaskOut.model_validate(t) for t in overdue],
        "scheduled": [TaskOut.model_validate(t) for t in scheduled],
        "open_count": len(open_tasks),
    }
