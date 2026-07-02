"""User-scoped project CRUD."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import memory_service
from app.services.llm import llm

router = APIRouter(prefix="/projects", tags=["projects"])


async def _get_owned(db: AsyncSession, user: User, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[Project]:
    result = await db.scalars(
        select(Project).where(Project.user_id == user.id).order_by(Project.created_at)
    )
    return list(result)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = Project(user_id=user.id, **payload.model_dump())
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # Remember the project so memory search can surface it later.
    summary = f"Project: {project.name}. {project.description or ''}".strip()
    await memory_service.remember(
        db, llm, user_id=user.id, kind="project", content=summary,
        source_type="project", source_id=project.id, project_id=project.id,
    )
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    return await _get_owned(db, user, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await _get_owned(db, user, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project = await _get_owned(db, user, project_id)
    await db.delete(project)
    await db.commit()
