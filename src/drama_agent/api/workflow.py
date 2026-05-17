import asyncio
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.models import Project
from drama_agent.workflow.graph import get_graph
from drama_agent.api.websocket import manager

router = APIRouter(prefix="/api/projects", tags=["workflow"])


class ResumeRequest(BaseModel):
    approved: bool
    notes: str = ""
    edited_prompts: dict[str, str] = {}


async def _run_workflow(project_id: str, initial_state: dict):
    """Run LangGraph workflow in background, broadcasting events via WebSocket."""
    from drama_agent.db.session import AsyncSessionLocal
    from drama_agent.db.models import Project
    from sqlalchemy import select

    graph = await get_graph()
    config = {"configurable": {"thread_id": project_id}}

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "analyzing"
            await db.commit()

    try:
        async for event in graph.astream(initial_state, config=config, stream_mode="values"):
            current_stage = event.get("current_stage", "")
            await manager.broadcast(project_id, "stage_change", {
                "stage": current_stage,
                "state": _safe_state_summary(event),
            })
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Project).where(Project.id == project_id))
                project = result.scalar_one_or_none()
                if project:
                    project.status = current_stage
                    project.state_snapshot = _safe_state_summary(event)
                    await db.commit()
    except Exception as e:
        await manager.broadcast(project_id, "error", {"message": str(e)})
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if project:
                project.status = "failed"
                project.error_message = str(e)
                await db.commit()


def _safe_state_summary(state: dict) -> dict:
    return {
        "title": state.get("title"),
        "current_stage": state.get("current_stage"),
        "story_analysis": state.get("story_analysis"),
        "screenplay": state.get("screenplay"),
        "shots": state.get("shots", []),
        "prompts": state.get("prompts", []),
        "videos": state.get("videos", []),
        "assembled_video_path": state.get("assembled_video_path"),
    }


@router.post("/{project_id}/workflow/start")
async def start_workflow(project_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "created":
        raise HTTPException(status_code=409, detail=f"Workflow already started (status: {project.status})")

    existing_refs = (project.state_snapshot or {}).get("character_references", {})

    initial_state = {
        "project_id": project_id,
        "title": project.title,
        "raw_input": project.raw_input,
        "genre": project.genre,
        "story_analysis": None,
        "screenplay": "",
        "screenplay_approved": False,
        "screenplay_revision_notes": "",
        "shots": [],
        "prompts": [],
        "prompts_approved": False,
        "prompt_revision_notes": "",
        "videos": [],
        "character_references": existing_refs,
        "current_stage": "starting",
        "error": None,
        "llm_model": project.llm_model,
        "video_model": project.video_model,
        "video_provider": project.video_provider,
        "assembled_video_path": None,
    }

    background_tasks.add_task(_run_workflow, project_id, initial_state)
    return {"ok": True, "message": "Workflow started"}


async def _resume_workflow(project_id: str, approved: bool, notes: str, edited_prompts: dict):
    """Resume a paused LangGraph workflow after human review."""
    from langgraph.types import Command
    from drama_agent.db.session import AsyncSessionLocal
    from drama_agent.db.models import Project as Proj
    from sqlalchemy import select as sel

    graph = await get_graph()
    config = {"configurable": {"thread_id": project_id}}
    resume_data = {"approved": approved, "notes": notes, "edited_prompts": edited_prompts}
    try:
        async for event in graph.astream(
            Command(resume=resume_data), config=config, stream_mode="values"
        ):
            current_stage = event.get("current_stage", "")
            await manager.broadcast(project_id, "stage_change", {
                "stage": current_stage,
                "state": _safe_state_summary(event),
            })
            async with AsyncSessionLocal() as db:
                res = await db.execute(sel(Proj).where(Proj.id == project_id))
                p = res.scalar_one_or_none()
                if p:
                    p.status = current_stage
                    p.state_snapshot = _safe_state_summary(event)
                    await db.commit()
    except Exception as e:
        await manager.broadcast(project_id, "error", {"message": str(e)})
        # Update DB status to failed so the UI reflects the error
        async with AsyncSessionLocal() as db:
            res = await db.execute(sel(Proj).where(Proj.id == project_id))
            p = res.scalar_one_or_none()
            if p:
                p.status = "failed"
                p.error_message = str(e)
                await db.commit()


@router.post("/{project_id}/workflow/resume")
async def resume_workflow(
    project_id: str,
    req: ResumeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Resume workflow after human review interrupt."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    background_tasks.add_task(
        _resume_workflow, project_id, req.approved, req.notes, req.edited_prompts
    )
    return {"ok": True, "message": "Workflow resumed"}


@router.get("/{project_id}/workflow/status")
async def get_workflow_status(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    graph = await get_graph()
    config = {"configurable": {"thread_id": project_id}}
    try:
        state = await graph.aget_state(config)
        full_state = state.values if state else {}
    except Exception:
        full_state = {}

    return {
        "project_id": project_id,
        "db_status": project.status,
        "current_stage": full_state.get("current_stage"),
        "screenplay": full_state.get("screenplay"),
        "shots": full_state.get("shots", []),
        "prompts": full_state.get("prompts", []),
        "videos": full_state.get("videos", []),
        "assembled_video_path": full_state.get("assembled_video_path"),
        "story_analysis": full_state.get("story_analysis"),
        "character_references": full_state.get("character_references", {}),
        "next": list(state.next) if state else [],
    }
