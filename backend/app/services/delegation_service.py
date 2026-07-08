"""Task delegation between connected users. The assignee owns the task (so all
reminders/nudges work for them); the delegator tracks it via assigned_by_id.

Auto-accept within a connection: an assigned task is immediately active in the
assignee's list, tagged with the delegator. Escape hatch: the assignee can Return
it (it goes back to the delegator). The delegator can Revoke (reclaim) it too.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.services import connections_service


async def assign(db: AsyncSession, delegator: User, assignee: User, *, title: str,
                 reason: str | None = None, deadline: datetime | None = None,
                 priority: int = 3) -> Task:
    if assignee.id == delegator.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Assign to someone else.")
    if not await connections_service.are_connected(db, delegator.id, assignee.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You're not connected with {assignee.display_name}. Send a connection "
            "request first.")
    task = Task(
        user_id=assignee.id, title=title, reason=reason,
        priority=priority if 1 <= priority <= 4 else 3,
        importance="high" if priority == 1 else "medium",
        deadline=deadline, assigned_by_id=delegator.id,
        assignment_status="active", assigned_at=datetime.now(timezone.utc))
    task.history.append(TaskHistory(event="assigned", detail=delegator.display_name))
    db.add(task)
    db.add(Notification(
        user_id=assignee.id, kind="assignment_new", title="New task assigned",
        body=f"{delegator.display_name} assigned you “{title}”.", alert_level="call"))
    await db.commit()
    await db.refresh(task)
    return task


async def _reclaim(db: AsyncSession, task: Task) -> None:
    """Move a delegated task back to the delegator's own list."""
    task.user_id = task.assigned_by_id
    task.assigned_by_id = None
    task.assignment_status = "none"
    task.assigned_at = None


async def return_task(db: AsyncSession, assignee: User, task: Task) -> None:
    if task.user_id != assignee.id or not task.assigned_by_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not an assigned task of yours.")
    delegator_id = task.assigned_by_id
    db.add(TaskHistory(task_id=task.id, event="returned", detail=assignee.display_name))
    await _reclaim(db, task)
    db.add(Notification(
        user_id=delegator_id, kind="assignment_returned", title="Task returned",
        body=f"{assignee.display_name} returned “{task.title}” — it's back on your list."))
    await db.commit()


async def revoke(db: AsyncSession, delegator: User, task: Task) -> None:
    if task.assigned_by_id != delegator.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You didn't delegate this.")
    assignee_id = task.user_id
    db.add(TaskHistory(task_id=task.id, event="revoked", detail=delegator.display_name))
    await _reclaim(db, task)
    db.add(Notification(
        user_id=assignee_id, kind="assignment_revoked", title="Task taken back",
        body=f"{delegator.display_name} took back “{task.title}”."))
    await db.commit()


def notify_completed(db: AsyncSession, task: Task, completer: User) -> None:
    """Call before commit when an assigned task is completed — tell the delegator."""
    if task.assigned_by_id and task.assigned_by_id != completer.id:
        db.add(Notification(
            user_id=task.assigned_by_id, kind="assignment_done", title="Task done",
            body=f"{completer.display_name} finished “{task.title}”.", alert_level="call"))


def notify_deadline_changed(db: AsyncSession, task: Task, changer: User) -> None:
    """Call before commit when an assignee moves a delegated task's time."""
    if task.assigned_by_id and task.assigned_by_id != changer.id:
        when = task.deadline.date().isoformat() if task.deadline else "no date"
        db.add(Notification(
            user_id=task.assigned_by_id, kind="assignment_deadline_changed",
            title="Deadline changed",
            body=f"{changer.display_name} moved “{task.title}” to {when}."))
