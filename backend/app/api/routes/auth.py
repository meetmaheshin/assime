"""Register, login, and current-user/settings endpoints (multi-user)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import (
    SettingsUpdate,
    Token,
    UserLogin,
    UserOut,
    UserRegister,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> Token:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name,
        timezone=payload.timezone,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)) -> Token:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/me/profile")
async def my_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """What AARTH knows about you — auto-learned summary + your own notes."""
    from app.services import profile_service
    return {
        "summary": await profile_service.get_summary(db, user.id),
        "about": await profile_service.get_about(db, user.id),
    }


class AboutIn(BaseModel):
    about: str = ""


@router.put("/me/profile/about")
async def set_about(
    payload: AboutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The user's own 'train your AI about yourself' notes."""
    from app.services import profile_service
    return {"about": await profile_service.set_about(db, user, payload.about)}


@router.post("/me/profile/refresh")
async def refresh_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rebuild the learned profile now (used by the 'Refresh' button)."""
    from app.services import profile_service
    from app.services.llm import llm
    await profile_service.refresh(db, llm, user)
    return {"summary": await profile_service.get_summary(db, user.id)}


@router.patch("/me/settings", response_model=UserOut)
async def update_settings(
    payload: SettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    changes = payload.model_dump(exclude_unset=True)
    handle = changes.pop("handle", None)
    if "handle" in payload.model_fields_set:
        from app.services import connections_service
        await connections_service.set_handle(db, user, handle)  # normalize + uniqueness
    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/me/export")
async def export_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Everything AARTH holds about you — for portability/transparency."""
    from app.models.conversation import ConversationTurn
    from app.models.memory import Memory
    from app.models.task import Task
    from app.services import profile_service

    tasks = list(await db.scalars(select(Task).where(Task.user_id == user.id)))
    mems = list(await db.scalars(select(Memory).where(Memory.user_id == user.id)))
    turns = list(await db.scalars(
        select(ConversationTurn).where(ConversationTurn.user_id == user.id)
        .order_by(ConversationTurn.created_at)))
    return {
        "account": {"email": user.email, "display_name": user.display_name,
                    "assistant_name": user.assistant_name, "timezone": user.timezone},
        "profile_summary": await profile_service.get_summary(db, user.id),
        "tasks": [{"title": t.title, "reason": t.reason, "status": t.status,
                   "priority": t.priority,
                   "deadline": t.deadline.isoformat() if t.deadline else None,
                   "created_at": t.created_at.isoformat()} for t in tasks],
        "memories": [{"kind": m.kind, "content": m.content,
                      "created_at": m.created_at.isoformat()} for m in mems],
        "conversation": [{"role": t.role, "content": t.content,
                          "created_at": t.created_at.isoformat()} for t in turns],
    }


@router.delete("/me/data", status_code=status.HTTP_204_NO_CONTENT)
async def wipe_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Erase everything AARTH has learned + all tasks (keeps the account so the
    user can start fresh). Their right to be forgotten."""
    from sqlalchemy import delete as sqldelete

    from app.models.conversation import ConversationTurn
    from app.models.memory import Memory
    from app.models.notification import Notification
    from app.models.profile import UserProfile
    from app.models.task import Task

    for model in (Notification, ConversationTurn, Memory, UserProfile, Task):
        await db.execute(sqldelete(model).where(model.user_id == user.id))
    await db.commit()
