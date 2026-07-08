"""Connections API — the trust layer for delegation."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import connections_service

router = APIRouter(prefix="/connections", tags=["connections"])


class ConnectRequest(BaseModel):
    email: EmailStr


@router.post("/request")
async def create_request(
    payload: ConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await connections_service.request(db, user, payload.email)


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
