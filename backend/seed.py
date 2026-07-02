"""Seed a demo user with sample projects, tasks, and memories.

Idempotent: safe to run repeatedly. Run from backend/:
    .venv\\Scripts\\python.exe seed.py

Login afterwards with:  demo@jarvis.app  /  demo12345
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.project import Project
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import memory_service
from app.services.llm import llm

DEMO_EMAIL = "demo@jarvis.app"
DEMO_PASSWORD = "demo12345"


async def main() -> None:
    async with SessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing is not None:
            print(f"Demo user already exists: {DEMO_EMAIL} / {DEMO_PASSWORD}")
            return

        user = User(
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            display_name="Mahesh",
            timezone="Asia/Kolkata",
        )
        db.add(user)
        await db.flush()

        furmacie = Project(
            user_id=user.id, name="Furmacie",
            description="Client pharmacy platform launch", importance="high",
        )
        surepass = Project(
            user_id=user.id, name="Surepass",
            description="KYC / verification integration", importance="medium",
        )
        db.add_all([furmacie, surepass])
        await db.flush()
        for p in (furmacie, surepass):
            await memory_service.remember(
                db, llm, user_id=user.id, kind="project",
                content=f"Project: {p.name}. {p.description}",
                source_type="project", source_id=p.id, project_id=p.id, commit=False,
            )

        now = datetime.now(timezone.utc)
        seed_tasks = [
            ("Finish Furmacie homepage", "Blocks tomorrow's client launch", furmacie.id, 1, now + timedelta(days=1)),
            ("Deploy login tracking", "Product analytics for launch week", furmacie.id, 2, now + timedelta(days=2)),
            ("Review Surepass KYC proposal", "Decide before the vendor call Friday", surepass.id, 2, now + timedelta(days=3)),
            ("Research courier options", "Need shipping partner shortlisted", None, 3, None),
            ("CIBIL integration spike", "Was pending from yesterday", surepass.id, 3, now - timedelta(days=1)),
        ]
        for title, reason, pid, prio, deadline in seed_tasks:
            task = Task(
                user_id=user.id, project_id=pid, title=title, reason=reason,
                priority=prio, importance="high" if prio == 1 else "medium",
                deadline=deadline,
            )
            task.history.append(TaskHistory(event="created"))
            db.add(task)
            await db.flush()
            mem = await memory_service.remember(
                db, llm, user_id=user.id, kind="task",
                content=f"{title}. {reason}",
                source_type="task", source_id=task.id, project_id=pid, commit=False,
            )
            task.embedding_id = mem.id

        await db.commit()
        print(f"Seeded demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        print(f"  2 projects, {len(seed_tasks)} tasks with memories.")


if __name__ == "__main__":
    asyncio.run(main())
