"""Password hashing (bcrypt) and JWT encode/decode.

bcrypt is used directly instead of passlib to avoid the passlib+bcrypt version
detection issues on Python 3.12+.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt has a hard 72-byte limit on the input; longer passwords are truncated
# by the algorithm. We encode to utf-8 and let bcrypt handle it.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pw, hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    """subject is the user id (stringified UUID)."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(
        token, settings.secret_key, algorithms=[settings.jwt_algorithm]
    )
