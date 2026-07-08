"""Connections API — the trust layer for delegation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import connections_service

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectRequest(BaseModel):
    email: str | None = None
    handle: str | None = None


class InviteAccept(BaseModel):
    code: str


@router.post("/request")
async def create_request(
    payload: ConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await connections_service.request(
        db, user, email=payload.email, handle=payload.handle)


@router.get("/search")
async def search(
    q: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await connections_service.search(db, user, q)


@router.get("/invite")
async def my_invite(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    code = await connections_service.get_invite_code(db, user)
    base = str(request.base_url).rstrip("/")
    return {"code": code, "url": f"{base}/ui/?invite={code}"}


@router.post("/invite/accept")
async def accept_invite(
    payload: InviteAccept,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await connections_service.accept_invite(db, user, payload.code)


@router.get("")
async def list_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await connections_service.list_for_user(db, user)


@router.post("/{conn_id}/{action}")
async def respond(
    conn_id: uuid.UUID,
    action: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if action not in ("accept", "decline", "block", "remove"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad action")
    return await connections_service.respond(db, user, conn_id, action)
