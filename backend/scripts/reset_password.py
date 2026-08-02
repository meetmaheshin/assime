"""Manual password reset — the escape hatch for a locked-out user until a
self-serve email flow exists.

Usage (from the backend/ dir, with DATABASE_URL pointing at the target DB):
    python -m scripts.reset_password user@example.com "theNewPassword"

It hashes the new password the same way the app does and updates that user's
row. Prints an error if no such email exists.
"""
import asyncio
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User


async def _run(email: str, new_password: str) -> int:
    if len(new_password) < 6:
        print("Password must be at least 6 characters.")
        return 2
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == email.lower().strip()))
        if user is None:
            print(f"No user with email {email!r}.")
            return 1
        user.hashed_password = hash_password(new_password)
        await db.commit()
        print(f"✓ Password reset for {user.display_name} <{user.email}>. "
              "They can log in with the new password now.")
        return 0


def main() -> None:
    if len(sys.argv) != 3:
        print('Usage: python -m scripts.reset_password <email> "<new password>"')
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(sys.argv[1], sys.argv[2])))


if __name__ == "__main__":
    main()
