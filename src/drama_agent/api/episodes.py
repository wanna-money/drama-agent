"""集(Episode)子资源 CRUD。流水线端点在 workflow.py。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.models import Project, Episode, Job, Event, VideoArtifact, Script
from drama_agent.db.enums import LifecycleStatus
from drama_agent.services import episode_service, cost_service

router = APIRouter(prefix="/api/projects", tags=["episodes"])


class CreateEpisodeRequest(BaseModel):
    title: str
    script_id: str
    llm_model: str = "deepseek-v4-pro"
    video_provider: str = "seedance"
    video_model: str = ""
    resolution: str = "768P"
    episode_number: int | None = None
    use_keyframes: bool = False
    keyframe_image_model: str = ""


@router.get("/{project_id}/episodes")
async def list_episodes(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    episodes = await episode_service.list_by_project(db, project_id)
    # 逐集算成本(N+1;单项目集数量级小,先接受)
    for e in episodes:
        agg = await cost_service.aggregate_entity(db, e["id"])
        e["cost_total"] = agg["total"]
        e["cost_unpriced"] = agg["unpriced"]
    return episodes


@router.post("/{project_id}/episodes", response_model=dict)
async def create_episode(
    project_id: str, req: CreateEpisodeRequest, db: AsyncSession = Depends(get_db)
):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    script = (await db.execute(
        select(Script).where(Script.id == req.script_id)
    )).scalar_one_or_none()
    if not script or script.status != LifecycleStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Script must be a completed script")
    return await episode_service.create(
        db, project_id=project_id, title=req.title, script_id=req.script_id,
        llm_model=req.llm_model, video_provider=req.video_provider,
        video_model=req.video_model, resolution=req.resolution,
        episode_number=req.episode_number,
        use_keyframes=req.use_keyframes,
        keyframe_image_model=req.keyframe_image_model,
    )


@router.get("/{project_id}/episodes/{episode_id}")
async def get_episode(project_id: str, episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = await episode_service.get(db, episode_id)
    if not ep or ep["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    agg = await cost_service.aggregate_entity(db, episode_id)
    return {**ep, "cost_total": agg["total"], "cost_unpriced": agg["unpriced"]}


@router.delete("/{project_id}/episodes/{episode_id}")
async def delete_episode(project_id: str, episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = (await db.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    if not ep or ep.project_id != project_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    # 级联清理该集的 jobs/events/artifacts
    await db.execute(delete(Job).where(Job.episode_id == episode_id))
    await db.execute(delete(Event).where(Event.episode_id == episode_id))
    await db.execute(delete(VideoArtifact).where(VideoArtifact.episode_id == episode_id))
    await db.delete(ep)
    await db.commit()
    return {"ok": True}
