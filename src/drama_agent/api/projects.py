import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.models import Project
from drama_agent.config import settings

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str
    raw_input: str
    genre: str = "drama"
    llm_model: str = "deepseek-v4-pro"
    video_provider: str = "seedance"
    video_model: str = ""


class ProjectResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    title: str
    status: str
    genre: str
    llm_model: str
    video_provider: str
    created_at: str
    updated_at: str


@router.post("", response_model=dict)
async def create_project(req: CreateProjectRequest, db: AsyncSession = Depends(get_db)):
    project = Project(
        id=str(uuid.uuid4()),
        title=req.title,
        raw_input=req.raw_input,
        genre=req.genre,
        llm_model=req.llm_model,
        video_provider=req.video_provider,
        video_model=req.video_model,
        status="created",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {
        "id": project.id,
        "title": project.title,
        "status": project.status,
        "genre": project.genre,
        "llm_model": project.llm_model,
        "video_provider": project.video_provider,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "status": p.status,
            "genre": p.genre,
            "video_provider": p.video_provider,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": project.id,
        "title": project.title,
        "raw_input": project.raw_input,
        "status": project.status,
        "genre": project.genre,
        "llm_model": project.llm_model,
        "video_provider": project.video_provider,
        "state_snapshot": project.state_snapshot,
        "error_message": project.error_message,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
    await db.commit()
    return {"ok": True}
