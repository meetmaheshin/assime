"""Send Web Push notifications (VAPID) so reminders reach a closed app."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.push import PushSubscription


def _vapid_private_str() -> str:
    """pywebpush wants the raw 32-byte private key, base64url-encoded."""
    pem = base64.b64decode(settings.vapid_private_key_b64)
    key = load_pem_private_key(pem, password=None)
    d = key.private_numbers().private_value
    return base64.urlsafe_b64encode(d.to_bytes(32, "big")).decode().rstrip("=")


_VAPID_PRIV = _vapid_private_str() if settings.push_enabled else ""


def _send_sync(sub_info: dict, payload: dict) -> None:
    webpush(
        subscription_info=sub_info,
        data=json.dumps(payload),
        vapid_private_key=_VAPID_PRIV,
        vapid_claims={"sub": settings.vapid_subject},
        ttl=600,
    )


async def push_to_user(
    db: AsyncSession, user_id: uuid.UUID, title: str, body: str, url: str = "/ui/"
) -> int:
    """Push to every device the user registered. Prunes dead subscriptions.
    Returns how many were delivered."""
    if not settings.push_enabled:
        return 0
    subs = list(await db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user_id)))
    payload = {"title": title, "body": body, "url": url}
    delivered, dead = 0, []
    for s in subs:
        info = {"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}}
        try:
            await asyncio.to_thread(_send_sync, info, payload)
            delivered += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):  # gone — drop it
                dead.append(s.id)
            else:
                logging.warning("push failed (%s): %s", code, e)
        except Exception as e:  # noqa: BLE001
            logging.warning("push error: %s", e)
    if dead:
        await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
        await db.commit()
    return delivered
