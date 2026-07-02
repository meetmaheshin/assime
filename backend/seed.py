"""Seed a demo user with sample projects, tasks, meetings, and memories.

Idempotent: safe to run repeatedly. Run from backend/:
    .venv\\Scripts\\python.exe seed.py

Login afterwards with:  demo@aath.app  /  demo12345
"""
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.meeting import Meeting
from app.models.project import Project
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import memory_service
from app.services.llm import llm

DEMO_EMAIL = "demo@aath.app"
DEMO_PASSWORD = "demo12345"
TZ = "Asia/Kolkata"


async def _create_user(db) -> User:
    user = User(
        email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD),
        display_name="Mahesh", timezone=TZ,
    )
    db.add(user)
    await db.flush()

    furmacie = Project(user_id=user.id, name="Furmacie",
                       description="Client pharmacy platform launch", importance="high")
    surepass = Project(user_id=user.id, name="Surepass",
                       description="KYC / verification integration", importance="medium")
    db.add_all([furmacie, surepass])
    await db.flush()
    for p in (furmacie, surepass):
        await memory_service.remember(
            db, llm, user_id=user.id, kind="project",
            content=f"Project: {p.name}. {p.description}",
            source_type="project", source_id=p.id, project_id=p.id, commit=False)

    now = datetime.now(timezone.utc)
    seed_tasks = [
        ("Finish Furmacie homepage", "Blocks tomorrow's client launch", furmacie.id, 1, now + timedelta(days=1)),
        ("Deploy login tracking", "Product analytics for launch week", furmacie.id, 2, now + timedelta(days=2)),
        ("Review Surepass KYC proposal", "Decide before the vendor call Friday", surepass.id, 2, now + timedelta(days=3)),
        ("Research courier options", "Need shipping partner shortlisted", None, 3, None),
        ("CIBIL integration spike", "Was pending from yesterday", surepass.id, 3, now - timedelta(days=1)),
    ]
    for title, reason, pid, prio, deadline in seed_tasks:
        task = Task(user_id=user.id, project_id=pid, title=title, reason=reason,
                    priority=prio, importance="high" if prio == 1 else "medium",
                    deadline=deadline)
        task.history.append(TaskHistory(event="created"))
        db.add(task)
        await db.flush()
        mem = await memory_service.remember(
            db, llm, user_id=user.id, kind="task", content=f"{title}. {reason}",
            source_type="task", source_id=task.id, project_id=pid, commit=False)
        task.embedding_id = mem.id
    await db.commit()
    print(f"Seeded demo user: {DEMO_EMAIL} / {DEMO_PASSWORD} (2 projects, {len(seed_tasks)} tasks)")
    return user


async def _ensure_meetings_today(db, user: User) -> None:
    local_now = datetime.now(ZoneInfo(TZ))
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)
    count = await db.scalar(select(func.count(Meeting.id)).where(
        Meeting.user_id == user.id, Meeting.starts_at >= day_start,
        Meeting.starts_at < day_end))
    if count:
        return
    def at(h, m=0):
        return local_now.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)
    db.add_all([
        Meeting(user_id=user.id, title="Client call — Furmacie launch", starts_at=at(10, 30),
                notes="Confirm homepage + go-live checklist"),
        Meeting(user_id=user.id, title="Standup", starts_at=at(15, 0)),
    ])
    await db.commit()
    print("Added 2 meetings for today.")


async def main() -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = await _create_user(db)
        else:
            print(f"Demo user already exists: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        await _ensure_meetings_today(db, user)


if __name__ == "__main__":
    asyncio.run(main())
