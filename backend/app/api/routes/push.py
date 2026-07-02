"""Web Push: expose the VAPID key, register device subscriptions, test."""
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.push import PushSubscription
from app.models.user import User
from app.services import push as push_svc

router = APIRouter(prefix="/push", tags=["push"])


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: dict  # {"p256dh": "...", "auth": "..."}


@router.get("/key")
async def vapid_key() -> dict:
    return {"key": settings.vapid_public_key, "enabled": settings.push_enabled}


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe(
    sub: SubscriptionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    p256dh = sub.keys.get("p256dh", "")
    auth = sub.keys.get("auth", "")
    existing = await db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == sub.endpoint))
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.add(PushSubscription(user_id=user.id, endpoint=sub.endpoint,
                                p256dh=p256dh, auth=auth))
    await db.commit()
    return {"ok": True}


@router.post("/test")
async def test_push(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    delivered = await push_svc.push_to_user(
        db, user.id, "AARTH", "Push notifications are working ✅")
    return {"delivered": delivered}
