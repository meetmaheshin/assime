"""Native push via Firebase Cloud Messaging (HTTP v1). Auth'd with the
service-account key using PyJWT (RS256) + httpx — no extra dependencies.

This is the one channel that can wake a CLOSED app for a server-side event
(someone assigns you a task, completes it, sends a connection request, etc.).
"""
from __future__ import annotations

import json
import logging
import time

import httpx
import jwt
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.fcm_token import FcmToken

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_cache: dict = {"access_token": None, "exp": 0, "project": None}


async def _access_token() -> tuple[str, str]:
    """OAuth access token for FCM, cached ~55 min. Returns (token, project_id)."""
    now = int(time.time())
    if _cache["access_token"] and _cache["exp"] > now + 60:
        return _cache["access_token"], _cache["project"]
    sa = json.loads(settings.firebase_service_account_json)
    token_uri = sa.get("token_uri", _TOKEN_URI)
    assertion = jwt.encode(
        {"iss": sa["client_email"], "scope": _SCOPE, "aud": token_uri,
         "iat": now, "exp": now + 3600},
        sa["private_key"], algorithm="RS256")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(token_uri, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion})
        r.raise_for_status()
        at = r.json()["access_token"]
    _cache.update(access_token=at, exp=now + 3300, project=sa["project_id"])
    return at, sa["project_id"]


async def send_to_user(db: AsyncSession, user_id, title: str, body: str,
                       data: dict | None = None, alert: str = "normal") -> int:
    """Push to every device the user has registered. Prunes dead tokens.

    Sent as a DATA-only message (no `notification` block) so the app's native
    AarthMessagingService.onMessageReceived runs even when the app is CLOSED —
    that's what lets `alert="call"` launch the full-screen ringing screen over
    the lock screen. A `notification` message would only reach the tray when
    backgrounded and never run our code.
    """
    if not settings.fcm_enabled:
        return 0
    tokens = list(await db.scalars(
        select(FcmToken).where(FcmToken.user_id == user_id)))
    if not tokens:
        return 0
    try:
        access_token, project = await _access_token()
    except Exception:
        logging.exception("FCM auth failed")
        return 0
    url = f"https://fcm.googleapis.com/v1/projects/{project}/messages:send"
    headers = {"Authorization": f"Bearer {access_token}"}
    payload = {"title": title, "body": body, "alert": alert}
    if data:
        payload.update({k: str(v) for k, v in data.items()})
    sent, dead = 0, []
    async with httpx.AsyncClient(timeout=15) as client:
        for t in tokens:
            message = {"message": {
                "token": t.token,
                # No `notification` block — data-only wakes our service when closed.
                "android": {"priority": "high"},
                "data": payload}}
            try:
                r = await client.post(url, headers=headers, json=message)
                if r.status_code == 200:
                    sent += 1
                elif r.status_code == 404 or "UNREGISTERED" in r.text:
                    dead.append(t.token)
                else:
                    logging.warning("FCM send %s: %s", r.status_code, r.text[:200])
            except Exception:
                logging.exception("FCM send error")
    if dead:
        await db.execute(delete(FcmToken).where(FcmToken.token.in_(dead)))
        await db.commit()
    return sent
