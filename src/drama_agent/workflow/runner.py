"""工作流执行核心:按 job.kind 路由到 ScriptGraph(写 Script)或 VideoGraph(写 Episode)。

thread_id = 实体 id(script 作业=script_id,video 作业=episode_id;均放在 job["episode_id"] 字段承载)。
状态变更 + 事件同事务写(S2)。调度在 worker,不在此。
"""
from langgraph.types import Command
from sqlalchemy import select
from drama_agent.db import session as db_session
from drama_agent.db.models import Episode, Project, Script
from drama_agent.db.enums import LifecycleStatus, JobKind, EventType, Genre
from drama_agent.services import event_service
from drama_agent.workflow.graph import get_script_graph, get_video_graph
from drama_agent.workflow.usage_context import set_usage_context
import structlog

logger = structlog.get_logger()

SCRIPT_KINDS = {JobKind.SCRIPT_START.value, JobKind.SCRIPT_RESUME.value}
RESUME_KINDS = {JobKind.RESUME.value, JobKind.SCRIPT_RESUME.value}


def _summary(state: dict) -> dict:
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


async def _persist(
    entity_id: str, project_id: str, is_script: bool,
    status: LifecycleStatus, event_type: EventType, payload: dict,
) -> None:
    """写实体(Script/Episode)status+snapshot + 事件同事务。"""
    async with db_session.AsyncSessionLocal() as db:
        row: Script | Episode | None
        if is_script:
            row = (await db.execute(
                select(Script).where(Script.id == entity_id)
            )).scalar_one_or_none()
        else:
            row = (await db.execute(
                select(Episode).where(Episode.id == entity_id)
            )).scalar_one_or_none()
        if row:
            row.status = status.value
            row.state_snapshot = payload
            await db.flush()
        await event_service.append_event(db, entity_id, event_type, payload, project_id=project_id)


async def _finalize_script(script_id: str, values: dict) -> None:
    """ScriptGraph 完成:落剧本正文 + 分析到 Script。"""
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(select(Script).where(Script.id == script_id))).scalar_one_or_none()
        if row:
            row.content = values.get("screenplay")
            row.story_analysis = values.get("story_analysis")
            await db.commit()


async def run_job(job: dict) -> None:
    entity_id = job["episode_id"]          # script 作业时承载 script_id
    project_id = job.get("project_id", "")
    is_script = job["kind"] in SCRIPT_KINDS
    graph = await (get_script_graph() if is_script else get_video_graph())
    config = {"configurable": {"thread_id": entity_id}}

    stream_input: Command | dict
    if job["kind"] in RESUME_KINDS:
        stream_input = Command(resume=job.get("payload_json") or {})
    else:
        stream_input = await (
            _build_script_initial_state(entity_id) if is_script
            else _build_video_initial_state(entity_id)
        )

    # 首个事件在第一个节点跑完后才到,故先置一次归属;随后每事件按 current_stage 刷新。
    set_usage_context(entity_id=entity_id, project_id=project_id, is_script=is_script, node="")

    async for event in graph.astream(stream_input, config=config, stream_mode="values"):
        set_usage_context(entity_id=entity_id, project_id=project_id, is_script=is_script,
                          node=(event.get("current_stage") or ""))
        await _persist(entity_id, project_id, is_script, LifecycleStatus.RUNNING,
                       EventType.STAGE_CHANGE, _summary(event))

    state = await graph.aget_state(config)
    values = state.values if state and getattr(state, "values", None) else {}
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if next_nodes:
        payload = _summary(values)
        payload["paused_at"] = next_nodes[0]
        await _persist(entity_id, project_id, is_script, LifecycleStatus.PAUSED,
                       EventType.PAUSED, payload)
    else:
        if is_script:
            await _finalize_script(entity_id, values)
        await _persist(entity_id, project_id, is_script, LifecycleStatus.COMPLETED,
                       EventType.COMPLETED, _summary(values))


def _fallback_llm_model() -> str:
    """script.llm_model 为空时的兜底:该 kind 有效默认(is_default → 首个可用)。"""
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    return dm.id if dm else ""


async def _build_script_initial_state(script_id: str) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        sc = (await db.execute(select(Script).where(Script.id == script_id))).scalar_one()
        proj = None
        if sc.project_id:
            proj = (await db.execute(
                select(Project).where(Project.id == sc.project_id)
            )).scalar_one_or_none()
        llm_model = sc.llm_model or _fallback_llm_model()
        return {
            "project_id": sc.project_id or "", "episode_id": script_id, "episode_number": 1,
            "title": sc.title, "raw_input": sc.source_text or "",
            "genre": sc.genre or (proj.genre if proj else Genre.DRAMA.value),
            "story_analysis": None, "screenplay": "",
            "screenplay_approved": False, "screenplay_revision_notes": "",
            "shots": [], "prompts": [], "prompts_approved": False,
            "prompt_revision_notes": "", "videos": [], "character_references": {},
            "current_stage": "starting", "error": None,
            "llm_model": llm_model, "video_model": "",
            "video_provider": "seedance", "resolution": "768P",
            "use_keyframes": False, "keyframe_image_model": "", "keyframes_approved": False,
            "look_assignments": {}, "look_assignments_approved": False, "assembled_video_path": None,
        }


async def _build_video_initial_state(episode_id: str) -> dict:
    async with db_session.AsyncSessionLocal() as db:
        ep = (await db.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
        sc = (await db.execute(
            select(Script).where(Script.id == ep.script_id)
        )).scalar_one_or_none()
        existing_refs = (ep.state_snapshot or {}).get("character_references", {})
        analysis = sc.story_analysis if sc else None
        screenplay = (sc.content if sc else "") or ""
        genre = analysis.get("genre") if isinstance(analysis, dict) else None
        return {
            "project_id": ep.project_id, "episode_id": episode_id,
            "episode_number": ep.episode_number, "title": ep.title, "raw_input": "",
            "genre": genre or Genre.DRAMA.value,
            "story_analysis": analysis, "screenplay": screenplay,
            "screenplay_approved": True, "screenplay_revision_notes": "",
            "shots": [], "prompts": [], "prompts_approved": False,
            "prompt_revision_notes": "", "videos": [], "character_references": existing_refs,
            "current_stage": "storyboard_start", "error": None,
            "llm_model": ep.llm_model, "video_model": ep.video_model,
            "video_provider": ep.video_provider, "resolution": ep.resolution,
            "use_keyframes": ep.use_keyframes, "keyframe_image_model": ep.keyframe_image_model,
            "keyframes_approved": False, "look_assignments": {},
            "look_assignments_approved": False, "assembled_video_path": None,
        }
