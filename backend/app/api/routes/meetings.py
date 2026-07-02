"""Meetings CRUD (minimal) — surfaced in the morning briefing and /today."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.meeting import MeetingCreate, MeetingOut

router = APIRouter(prefix="/meetings", tags=["meetings"])


@router.get("", response_model=list[MeetingOut])
async def list_upcoming(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Meeting]:
    now = datetime.now(timezone.utc)
    rows = await db.scalars(
        select(Meeting)
        .where(Meeting.user_id == user.id, Meeting.starts_at >= now)
        .order_by(Meeting.starts_at)
        .limit(20)
    )
    return list(rows)


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Meeting:
    meeting = Meeting(user_id=user.id, **payload.model_dump())
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return meeting
