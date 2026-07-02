"""User-scoped task CRUD with duplicate detection, completion, and overdue reasons."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.task import Task, TaskHistory
from app.models.user import User
from app.schemas.capture import CaptureDraft, CaptureRequest, CaptureResponse
from app.schemas.task import (
    DuplicateMatch,
    OverdueReason,
    TaskCreate,
    TaskCreateResult,
    TaskOut,
    TaskUpdate,
)
from app.services import capture as capture_svc
from app.services import memory_service
from app.services.llm import llm

router = APIRouter(prefix="/tasks", tags=["tasks"])

_VALID_REASONS = {
    "blocked", "forgot", "too_busy", "waiting", "not_important", "other",
}


async def _get_owned(db: AsyncSession, user: User, task_id: uuid.UUID) -> Task:
    # Eager-load history so mutation endpoints can append to it without an
    # illegal lazy-load in the async session.
    task = await db.scalar(
        select(Task).options(selectinload(Task.history)).where(Task.id == task_id)
    )
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return task


def _log(task: Task, event: str, detail: str | None = None,
         reason_code: str | None = None) -> None:
    task.history.append(
        TaskHistory(event=event, detail=detail, reason_code=reason_code)
    )


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status_filter: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Task]:
    stmt = select(Task).where(Task.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    stmt = stmt.order_by(Task.priority, Task.deadline.nulls_last())
    return list(await db.scalars(stmt))


@router.post("", response_model=TaskCreateResult, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskCreateResult:
    probe = f"{payload.title}. {payload.description or ''}".strip()

    # Duplicate detection: never blindly duplicate work (PRD). If similar tasks
    # exist and the client hasn't forced creation, return matches so the UI can
    # ask same / new / follow-up.
    if not payload.skip_duplicate_check:
        dupes = await memory_service.find_duplicates(
            db, llm, user_id=user.id, text=probe
        )
        if dupes:
            matches = []
            for mem, sim in dupes:
                dup_task = (
                    await db.get(Task, mem.source_id) if mem.source_id else None
                )
                if dup_task is not None:
                    matches.append(
                        DuplicateMatch(
                            id=dup_task.id, title=dup_task.title,
                            similarity=round(sim, 3), status=dup_task.status,
                        )
                    )
            if matches:
                return TaskCreateResult(task=None, possible_duplicates=matches)

    task = Task(
        user_id=user.id,
        **payload.model_dump(exclude={"skip_duplicate_check"}),
    )
    _log(task, "created")
    db.add(task)
    await db.flush()

    mem = await memory_service.remember(
        db, llm, user_id=user.id, kind="task", content=probe,
        source_type="task", source_id=task.id, project_id=task.project_id,
        commit=False,
    )
    task.embedding_id = mem.id
    await db.commit()
    await db.refresh(task)
    return TaskCreateResult(task=TaskOut.model_validate(task))


async def _persist_task(db: AsyncSession, user: User, draft: CaptureDraft) -> Task:
    task = Task(
        user_id=user.id, title=draft.title, reason=draft.reason,
        priority=draft.priority, deadline=draft.deadline,
        importance="high" if draft.priority == 1 else "medium",
    )
    _log(task, "created")
    db.add(task)
    await db.flush()
    probe = f"{draft.title}. {draft.reason or ''}".strip()
    mem = await memory_service.remember(
        db, llm, user_id=user.id, kind="task", content=probe,
        source_type="task", source_id=task.id, commit=False,
    )
    task.embedding_id = mem.id
    await db.commit()
    await db.refresh(task)
    return task


_SKIP_REASON = {"no", "skip", "none", "nothing", "n/a", "-"}


@router.post("/capture", response_model=CaptureResponse)
async def capture_task(
    payload: CaptureRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaptureResponse:
    """Conversational (voice) task capture: extract a task from natural speech,
    ask back for the 'why' if it's missing, then save (with dedupe)."""
    now = datetime.now(timezone.utc)
    draft = payload.draft or CaptureDraft()
    utter = payload.utterance.strip()
    answering = draft.pending

    # Confirm-create: user accepted a possible-duplicate as new. Persist directly.
    if payload.skip_duplicate_check and draft.title:
        task = await _persist_task(db, user, draft)
        return CaptureResponse(action="created", draft=draft,
                               task=TaskOut.model_validate(task))

    if answering == "reason":
        draft.reason = None if utter.lower() in _SKIP_REASON else utter
        draft.pending = None
    else:
        fields = await capture_svc.extract_fields(llm, utter, now)
        if answering == "title":
            draft.title = fields["title"] or utter or "New task"
        else:
            draft.title = fields["title"]
        draft.reason = draft.reason or fields["reason"]
        draft.priority = fields["priority"]
        draft.deadline = fields["deadline"]
        draft.pending = None

    # Ask back for what's missing (title, then the 'why') — never guess the why.
    if not draft.title:
        draft.pending = "title"
        return CaptureResponse(action="ask", draft=draft,
                               question="What would you like me to add?")
    if not draft.reason and answering != "reason":
        draft.pending = "reason"
        return CaptureResponse(
            action="ask", draft=draft,
            question=f"Got it — “{draft.title}”. Why does it matter?",
        )

    # Duplicate detection before saving (never blindly duplicate).
    if not payload.skip_duplicate_check:
        probe = f"{draft.title}. {draft.reason or ''}".strip()
        dupes = await memory_service.find_duplicates(db, llm, user_id=user.id, text=probe)
        matches = []
        for mem, sim in dupes:
            dt = await db.get(Task, mem.source_id) if mem.source_id else None
            if dt is not None:
                matches.append(DuplicateMatch(
                    id=dt.id, title=dt.title, similarity=round(sim, 3), status=dt.status))
        if matches:
            return CaptureResponse(action="duplicate", draft=draft,
                                   possible_duplicates=matches)

    task = await _persist_task(db, user, draft)
    return CaptureResponse(action="created", draft=draft,
                           task=TaskOut.model_validate(task))


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Task:
    return await _get_owned(db, user, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Task:
    task = await _get_owned(db, user, task_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(task, field, value)
    if "status" in changes:
        _log(task, "status_changed", detail=changes["status"])
    if "deadline" in changes:
        _log(task, "deadline_moved")
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Explicit completion — never assume completion (PRD AI behaviour)."""
    task = await _get_owned(db, user, task_id)
    task.status = "completed"
    task.progress = 100
    task.completed_at = datetime.now(timezone.utc)
    _log(task, "completed")
    await db.commit()
    await db.refresh(task)
    return task


@router.post("/{task_id}/overdue-reason", response_model=TaskOut)
async def record_overdue_reason(
    task_id: uuid.UUID,
    payload: OverdueReason,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Task:
    """Accountability flow: store why a task slipped."""
    if payload.reason_code not in _VALID_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"reason_code must be one of {sorted(_VALID_REASONS)}",
        )
    task = await _get_owned(db, user, task_id)
    _log(task, "overdue_reason", detail=payload.detail, reason_code=payload.reason_code)
    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await _get_owned(db, user, task_id)
    await db.delete(task)
    await db.commit()
