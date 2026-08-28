"""项目(剧集元信息)CRUD。单集流水线在 episodes.py + workflow.py。"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel, Field
from drama_agent.db.session import get_db
from drama_agent.db.models import Project, Episode, Job, Event, VideoArtifact
from drama_agent.db.enums import Genre
from drama_agent.services import episode_service, cost_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str
    genre: Genre = Genre.DRAMA   # 非法值由 pydantic 拒为 422
    # 小说模式(可选):有正文时切分依据须恰好二选一
    source_text: str | None = None
    # 必须为正数:非正值会原样进改编 prompt(如"切成恰好 -3 集"),且 0 会被下面的
    # bool() 二选一校验当成"没给"
    target_episodes: int | None = Field(default=None, gt=0)
    target_seconds_per_episode: int | None = Field(default=None, gt=0)


@router.post("", response_model=dict)
async def create_project(req: CreateProjectRequest, db: AsyncSession = Depends(get_db)):
    if (req.source_text or "").strip() and (
        bool(req.target_episodes) == bool(req.target_seconds_per_episode)
    ):
        raise HTTPException(status_code=422, detail="切分依据须二选一:集数 或 每集时长")
    project = Project(
        id=str(uuid.uuid4()), title=req.title, genre=req.genre.value,
        source_text=req.source_text,
        target_episodes=req.target_episodes,
        target_seconds_per_episode=req.target_seconds_per_episode,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "status": "empty",  # 新项目还没有集
        "adaptation_status": project.adaptation_status,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    projects = (await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )).scalars().all()
    out = []
    for p in projects:
        status = await episode_service.project_status(db, p.id)
        # 逐个项目算成本(N+1 查询;项目数量级小,先接受,必要时再改批量聚合)
        cost = await cost_service.project_total(db, p.id)
        out.append({
            "id": p.id,
            "title": p.title,
            "genre": p.genre,
            "status": status,
            "cost_total": cost["total"],
            "cost_unpriced": cost["unpriced"],
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        })
    return out


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    episodes = await episode_service.list_by_project(db, project_id)
    status = episode_service.aggregate_project_status([e["status"] for e in episodes])
    cost = await cost_service.project_total(db, project_id)
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "status": status,
        "episodes": episodes,
        "cost_total": cost["total"],
        "cost_unpriced": cost["unpriced"],
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 级联清理该项目下所有集及其 jobs/events/artifacts(事务内)
    await db.execute(delete(Job).where(Job.project_id == project_id))
    await db.execute(delete(Event).where(Event.project_id == project_id))
    await db.execute(delete(VideoArtifact).where(VideoArtifact.project_id == project_id))
    await db.execute(delete(Episode).where(Episode.project_id == project_id))
    await db.delete(project)
    await db.commit()
    return {"ok": True}
