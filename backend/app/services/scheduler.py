"""Background scheduler: every minute, generate due nudges for all users and
push any that haven't been delivered yet — so reminders fire even when nobody
has the app open. Single-instance (Railway) friendly.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.notification import Notification
from app.models.user import User
from app.services import fcm_service, nudges, push

_scheduler: AsyncIOScheduler | None = None


async def _tick() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    async with SessionLocal() as db:
        users = list(await db.scalars(select(User).where(User.is_active.is_(True))))
        for user in users:
            try:
                await nudges.generate(db, user)
            except Exception:
                logging.exception("nudge generation failed for %s", user.id)

            if not (settings.fcm_enabled or settings.push_enabled):
                continue
            # Deliver recent, still-pending, not-yet-pushed notifications (once each)
            # to the phone — native FCM preferred, web push as fallback.
            pending = list(await db.scalars(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.status == "pending",
                    Notification.pushed.is_(False),
                    Notification.created_at >= cutoff,
                )))
            for n in pending:
                try:
                    if settings.fcm_enabled:
                        await fcm_service.send_to_user(
                            db, user.id, n.title, n.body,
                            alert=n.alert_level or "normal")
                    elif settings.push_enabled:
                        await push.push_to_user(db, user.id, n.title, n.body)
                except Exception:
                    logging.exception("push failed for notification %s", n.id)
                n.pushed = True
            if pending:
                await db.commit()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None or not (settings.fcm_enabled or settings.push_enabled):
        return
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(_tick, "interval", seconds=60, id="nudge_push",
                       max_instances=1, coalesce=True)
    _scheduler.start()
    logging.info("nudge/push scheduler started")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
