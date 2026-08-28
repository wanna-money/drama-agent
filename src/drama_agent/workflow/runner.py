"""工作流执行核心:在统一制作图上跑一集,thread_id = episode_id。

图内部按"是否已有通过的剧本"分流(有 → 直达分镜;无 → 从故事分析开始),
故此处不再按 job.kind 挑图。状态变更 + 事件同事务写(S2)。调度在 worker,不在此。
"""
from langgraph.types import Command
from sqlalchemy import select
from drama_agent.db import session as db_session
from drama_agent.db.models import Episode, Script, Project
from drama_agent.db.enums import LifecycleStatus, JobKind, EventType, Genre, AdaptationStatus
from drama_agent.services import event_service, reference_service
from drama_agent.workflow.graph import get_graph
from drama_agent.workflow.usage_context import set_usage_context
import structlog

logger = structlog.get_logger()

RESUME_KINDS = {JobKind.RESUME.value}


def _summary(state: dict) -> dict:
    """写进 state_snapshot 的投影。**必须覆盖 /workflow/status 会读的每个字段** ——
    _persist 是整表覆盖,漏一个字段该字段在接口上就永远是空(见 test_runner 里的对齐测试)。
    """
    return {
        "title": state.get("title"),
        "current_stage": state.get("current_stage"),
        "story_analysis": state.get("story_analysis"),
        "screenplay": state.get("screenplay"),
        "shots": state.get("shots", []),
        "prompts": state.get("prompts", []),
        "videos": state.get("videos", []),
        # 参考图清单要进快照:_persist 是整表覆盖 state_snapshot,漏了它就会把开拍前
        # 绑好的参考图从快照里抹掉,只剩 checkpointer 一份(读不到图时面板就空了)。
        "references": state.get("references", []),
        "look_assignments": state.get("look_assignments", {}),
        # 阵容(角色名→character_id)与待确认清单:status 端点下发给确认面板
        "cast": state.get("cast", {}),
        "cast_pending": state.get("cast_pending", []),
        # 分镜总时长收敛结果:status 端点读 duration_over_target 提示"退回重做";
        # revision_notes 让前端能显示"分镜为何被打回"(与 references 同理,须进快照)。
        "duration_over_target": state.get("duration_over_target", False),
        "storyboard_revision_notes": state.get("storyboard_revision_notes", ""),
        "assembled_video_path": state.get("assembled_video_path"),
    }


async def _persist(
    entity_id: str, project_id: str,
    status: LifecycleStatus, event_type: EventType, payload: dict,
) -> None:
    """写 Episode status+snapshot + 事件同事务。"""
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Episode).where(Episode.id == entity_id)
        )).scalar_one_or_none()
        if row:
            row.status = status.value
            row.state_snapshot = payload
            await db.flush()
        await event_service.append_event(db, entity_id, event_type, payload, project_id=project_id)


async def run_job(job: dict) -> None:
    # 作品级改编:adapt job 的 episode_id 列载的是 project_id(见 db/enums.JobKind.ADAPT)
    if job["kind"] == JobKind.ADAPT.value:
        await _run_adaptation(job["episode_id"])
        return
    episode_id = job["episode_id"]
    project_id = job.get("project_id", "")
    graph = await get_graph()
    config = {"configurable": {"thread_id": episode_id}}

    stream_input: Command | dict
    if job["kind"] in RESUME_KINDS:
        stream_input = Command(resume=job.get("payload_json") or {})
    else:
        stream_input = await _build_initial_state(episode_id)

    # 首个事件在第一个节点跑完后才到,故先置一次归属;随后每事件按 current_stage 刷新。
    set_usage_context(entity_id=episode_id, project_id=project_id, is_script=False, node="")

    async for event in graph.astream(stream_input, config=config, stream_mode="values"):
        set_usage_context(entity_id=episode_id, project_id=project_id, is_script=False,
                          node=(event.get("current_stage") or ""))
        await _persist(episode_id, project_id, LifecycleStatus.RUNNING,
                       EventType.STAGE_CHANGE, _summary(event))

    state = await graph.aget_state(config)
    values = state.values if state and getattr(state, "values", None) else {}
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if next_nodes:
        payload = _summary(values)
        payload["paused_at"] = next_nodes[0]
        await _persist(episode_id, project_id, LifecycleStatus.PAUSED,
                       EventType.PAUSED, payload)
    else:
        await _persist(episode_id, project_id, LifecycleStatus.COMPLETED,
                       EventType.COMPLETED, _summary(values))


async def _run_adaptation(project_id: str) -> None:
    """作品级改编:跑 adaptation_service.adapt,结果写库 + 发事件。

    产出不可用由 adapt 内部落 failed;传输层异常在此先标 failed 再抛(交 job 重试),
    否则作品会永远停在 adapting。
    """
    from drama_agent.services import adaptation_service
    async with db_session.AsyncSessionLocal() as db:
        try:
            result = await adaptation_service.adapt(db, project_id)
        except Exception:
            await _mark_adaptation_failed(project_id)
            raise
        await event_service.append_event(
            db, project_id, EventType.STAGE_CHANGE,
            {"adaptation_status": result["adaptation_status"],
             "episodes": len(result["adapted_draft"])},
            project_id=project_id)


async def _mark_adaptation_failed(project_id: str) -> None:
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if row:
            row.adaptation_status = AdaptationStatus.FAILED.value
            await db.flush()
        await event_service.append_event(
            db, project_id, EventType.ERROR,
            {"adaptation_status": AdaptationStatus.FAILED.value}, project_id=project_id)


def _fallback_llm_model() -> str:
    """episode.llm_model 为空时的兜底:该 kind 有效默认(is_default → 首个可用)。"""
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    return dm.id if dm else ""


async def _build_initial_state(episode_id: str) -> dict:
    """本集的图初始状态。已有剧本正文的(改编切片种入版本 / 复用源剧本)带着正文进图并置
    screenplay_approved=True(图内直达分镜);都没有则只带原始故事,由 story_analyzer 起跑。
    分流判据必须与 graph.route_entry 一致 —— 那边只看 screenplay_approved。
    """
    async with db_session.AsyncSessionLocal() as db:
        ep = (await db.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
        sc = None
        if ep.script_id:
            sc = (await db.execute(
                select(Script).where(Script.id == ep.script_id)
            )).scalar_one_or_none()
        # 开拍前绑好的参考图带进图状态;reference_service 负责兼容旧 character_references 快照
        existing_refs = reference_service.stored(ep.state_snapshot)
        versions = ep.screenplay_versions or []
        if versions:                                   # 改编切片(建集时种入)
            screenplay = versions[ep.screenplay_version_current or 0].get("screenplay", "")
            approved = True
            analysis = None
        elif ep.script_id:                             # 复用剧本
            screenplay = (sc.content if sc else "") or ""
            approved = True
            analysis = sc.story_analysis if sc else None
        else:                                          # 从故事开始
            screenplay = ""
            approved = False
            analysis = None
        genre = analysis.get("genre") if isinstance(analysis, dict) else None
        return {
            "project_id": ep.project_id, "episode_id": episode_id,
            "episode_number": ep.episode_number, "title": ep.title,
            # 原始故事文本目前只存在源剧本上;Episode 自带 raw_input 由后续任务补(届时优先取它)
            "raw_input": (sc.source_text if sc else "") or "",
            "script_id": ep.script_id,
            "genre": genre or (sc.genre if sc else None) or Genre.DRAMA.value,
            "story_analysis": analysis, "screenplay": screenplay,
            "screenplay_approved": approved,
            "screenplay_revision_notes": "",
            "shots": [], "target_seconds": ep.target_seconds,
            "storyboard_approved": False, "duration_over_target": False,
            "storyboard_revision_notes": "",
            "prompts": [], "prompts_approved": False,
            "prompt_revision_notes": "", "videos": [], "references": existing_refs,
            "cast": {}, "cast_pending": [],
            "current_stage": "storyboard_start" if approved else "starting",
            "error": None,
            "llm_model": ep.llm_model or _fallback_llm_model(),
            "video_model": ep.video_model,
            "video_provider": ep.video_provider, "resolution": ep.resolution,
            "use_keyframes": ep.use_keyframes, "keyframe_image_model": ep.keyframe_image_model,
            "keyframes_approved": False, "look_assignments": {},
            "look_assignments_approved": False, "assembled_video_path": None,
        }
