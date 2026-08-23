from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.models import Episode
from drama_agent.db.enums import LifecycleStatus, JobKind, EventType
from drama_agent.services import job_service, event_service, cost_service
from drama_agent.workflow.graph import get_video_graph
from drama_agent.workflow.pipeline_steps import build_pipeline

router = APIRouter(prefix="/api/episodes", tags=["workflow"])


class ResumeRequest(BaseModel):
    approved: bool
    notes: str = ""
    edited_prompts: dict[str, str] = {}
    edited_negative_prompts: dict[str, str] = {}  # prompts_review:shot_id→编辑后的负向 prompt
    assignments: dict[str, dict[str, str]] = {}   # look_review:scene→char→look_id
    regenerate_shot_ids: list[str] = []           # keyframes_review:要重生成的镜头


async def _get_episode_or_404(db: AsyncSession, episode_id: str) -> Episode:
    ep = (await db.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Episode not found")
    return ep


@router.post("/{episode_id}/workflow/start")
async def start_workflow(episode_id: str, db: AsyncSession = Depends(get_db)):
    """入队一条 start job(幂等)。worker 后台领取执行。"""
    ep = await _get_episode_or_404(db, episode_id)
    if ep.status != LifecycleStatus.CREATED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow already started (status: {ep.status})",
        )
    job = await job_service.enqueue(
        db, JobKind.START, episode_id, dedup_key="start", project_id=ep.project_id
    )
    ep.status = LifecycleStatus.QUEUED.value
    await db.flush()
    await event_service.append_event(
        db, episode_id, EventType.STAGE_CHANGE, {"lifecycle": "queued"}, project_id=ep.project_id
    )
    return {"ok": True, "job_id": job["id"], "message": "Workflow queued"}


@router.post("/{episode_id}/workflow/resume")
async def resume_workflow(
    episode_id: str, req: ResumeRequest, db: AsyncSession = Depends(get_db)
):
    """人工审核后入队一条 resume job(幂等,dedup 按当前中断点)。"""
    ep = await _get_episode_or_404(db, episode_id)

    graph = await get_video_graph()
    config = {"configurable": {"thread_id": episode_id}}
    state = await graph.aget_state(config)
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if not next_nodes:
        raise HTTPException(status_code=409, detail="Workflow is not paused at a review step")

    dedup_key = "resume:" + "-".join(next_nodes)
    payload = {
        "approved": req.approved,
        "notes": req.notes,
        "edited_prompts": req.edited_prompts,
        "edited_negative_prompts": req.edited_negative_prompts,
        "assignments": req.assignments,
        "regenerate_shot_ids": req.regenerate_shot_ids,
    }
    job = await job_service.enqueue(
        db, JobKind.RESUME, episode_id, dedup_key=dedup_key, payload=payload,
        project_id=ep.project_id,
    )
    ep.status = LifecycleStatus.QUEUED.value
    await db.flush()
    await event_service.append_event(
        db, episode_id, EventType.STAGE_CHANGE, {"lifecycle": "queued", "resume": True},
        project_id=ep.project_id,
    )
    return {"ok": True, "job_id": job["id"], "message": "Workflow resume queued"}


@router.get("/{episode_id}/workflow/status")
async def get_workflow_status(episode_id: str, db: AsyncSession = Depends(get_db)):
    """轻量状态:读投影(Episode 生命周期 + 最近事件摘要),不反序列化整个图状态。"""
    ep = await _get_episode_or_404(db, episode_id)
    snapshot = ep.state_snapshot or {}
    current_stage = snapshot.get("current_stage")
    paused_at = snapshot.get("paused_at")
    agg = await cost_service.aggregate_entity(db, episode_id)
    return {
        "episode_id": episode_id,
        "project_id": ep.project_id,
        "db_status": ep.status,
        "current_stage": current_stage,
        "paused_at": paused_at,
        "shots": snapshot.get("shots", []),
        "prompts": snapshot.get("prompts", []),
        "videos": snapshot.get("videos", []),
        "assembled_video_path": snapshot.get("assembled_video_path"),
        "story_analysis": snapshot.get("story_analysis"),
        "screenplay": snapshot.get("screenplay"),
        "look_assignments": snapshot.get("look_assignments", {}),
        # 流水线步骤(单一真相在后端 pipeline_steps);中断时以 paused_at 作当前步。
        # by_node 的键是 current_stage,由 build_pipeline 按 stages 归并到步上。
        "pipeline": build_pipeline(
            ep.use_keyframes, paused_at or current_stage, costs=agg["by_node"]
        ),
        "cost_total": agg["total"],
        "cost_unpriced": agg["unpriced"],
        "cost_tokens_total": agg["tokens_total"],
        "cost_by_kind": agg["by_kind"],
        "error_message": ep.error_message,
    }


@router.get("/{episode_id}/workflow/state")
async def get_workflow_state(episode_id: str, db: AsyncSession = Depends(get_db)):
    """完整状态:从 checkpointer 读图(重操作,仅在需要完整 state 时用)。"""
    await _get_episode_or_404(db, episode_id)
    graph = await get_video_graph()
    config = {"configurable": {"thread_id": episode_id}}
    try:
        state = await graph.aget_state(config)
        full = state.values if state else {}
    except Exception:
        full = {}
    return {
        "episode_id": episode_id,
        "current_stage": full.get("current_stage"),
        "screenplay": full.get("screenplay"),
        "shots": full.get("shots", []),
        "prompts": full.get("prompts", []),
        "videos": full.get("videos", []),
        "assembled_video_path": full.get("assembled_video_path"),
        "story_analysis": full.get("story_analysis"),
        "character_references": full.get("character_references", {}),
        "next": list(state.next) if state else [],
    }


@router.get("/{episode_id}/workflow/events")
async def get_workflow_events(
    episode_id: str, after_seq: int = 0, db: AsyncSession = Depends(get_db)
):
    """游标补拉事件(WebSocket 重连也用此接口)。"""
    await _get_episode_or_404(db, episode_id)
    events = await event_service.fetch_since(db, episode_id, after_seq)
    return {"events": events}
