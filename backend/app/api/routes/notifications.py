"""Proactive notifications: list (auto-generates due nudges), respond, dismiss."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.notification import Notification
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.schemas.notification import NotificationOut, RespondRequest, RespondResult
from app.services import nudges

router = APIRouter(prefix="/notifications", tags=["notifications"])

_VALID_REASONS = {
    "blocked", "forgot", "too_busy", "waiting", "not_important", "other",
}

# Human, non-guilt-tripping acknowledgements per reason (PRD: never guilt-trip).
_ACK = {
    "blocked": "Got it — you're blocked. Want me to note what you're waiting on?",
    "forgot": "No worries, it happens. Want me to bump it to today?",
    "too_busy": "Understood — I'll keep it near the top for when you have a window.",
    "waiting": "Okay, waiting on someone else. I'll check back with you tomorrow.",
    "not_important": "Fair enough. Should I lower its priority or drop it?",
    "other": "Noted — I'll keep tracking it and check in again.",
}


async def _owned(db: AsyncSession, user: User, nid: uuid.UUID) -> Notification:
    n = await db.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return n


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    # Generate any due nudges first (lazy scheduler), then return recent ones.
    await nudges.generate(db, user)
    now = datetime.now(timezone.utc)
    rows = await db.scalars(
        select(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.status != "dismissed",
            or_(Notification.snoozed_until.is_(None),
                Notification.snoozed_until <= now),
        )
        .order_by(Notification.created_at.desc())
        .limit(30)
    )
    return list(rows)


@router.post("/run", response_model=list[NotificationOut])
async def run_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Notification]:
    """Demo helper: force-generate nudges now (ignores quiet hours / time windows)."""
    return await nudges.generate(db, user, force=True)


@router.post("/{nid}/respond", response_model=RespondResult)
async def respond(
    nid: uuid.UUID,
    payload: RespondRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RespondResult:
    n = await _owned(db, user, nid)
    message = "Thanks — noted."

    if n.kind == "overdue" and payload.reason_code:
        if payload.reason_code not in _VALID_REASONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"reason_code must be one of {sorted(_VALID_REASONS)}",
            )
        if n.task_id:
            db.add(TaskHistory(task_id=n.task_id, event="overdue_reason",
                               reason_code=payload.reason_code, detail=payload.text))
        message = _ACK.get(payload.reason_code, message)
    elif payload.text:
        message = "Great — logged. I'll factor that into tomorrow's plan."

    n.status = "answered"
    await db.commit()
    await db.refresh(n)
    return RespondResult(message=message, notification=NotificationOut.model_validate(n))


@router.post("/{nid}/snooze", response_model=NotificationOut)
async def snooze(
    nid: uuid.UUID,
    minutes: int = 10,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Notification:
    n = await _owned(db, user, nid)
    minutes = max(1, min(minutes, 24 * 60))
    n.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    n.status = "pending"
    await db.commit()
    await db.refresh(n)
    return n


@router.post("/{nid}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(
    nid: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    n = await _owned(db, user, nid)
    n.status = "dismissed"
    await db.commit()
