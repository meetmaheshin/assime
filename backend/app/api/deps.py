"""Shared FastAPI dependencies: DB session + authenticated current user."""
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=True)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_token(creds.credentials)
        subject = payload.get("sub")
        if subject is None:
            raise _CREDENTIALS_ERROR
        user_id = uuid.UUID(subject)
    except (jwt.PyJWTError, ValueError):
        raise _CREDENTIALS_ERROR

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user
