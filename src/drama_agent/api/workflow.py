from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from drama_agent import provider as provider_pkg
from drama_agent.db.session import get_db
from drama_agent.db.models import Episode
from drama_agent.db.enums import LifecycleStatus, JobKind, EventType
from drama_agent.services import (
    job_service, event_service, cost_service, reference_service,
    episode_service, text_revise_service,
)
from drama_agent.workflow.graph import get_graph
from drama_agent.workflow.pipeline_steps import build_pipeline

router = APIRouter(prefix="/api/episodes", tags=["workflow"])


class ResumeRequest(BaseModel):
    approved: bool
    notes: str = ""
    edited_prompts: dict[str, str] = {}
    edited_negative_prompts: dict[str, str] = {}  # prompts_review:shot_id→编辑后的负向 prompt
    assignments: dict[str, dict[str, str]] = {}   # look_review:scene→char→look_id
    regenerate_shot_ids: list[str] = []           # keyframes_review:要重生成的镜头
    # cast_review:角色名→{action: link|create, character_id?}
    cast: dict[str, dict[str, str]] = {}


class ReviseMessage(BaseModel):
    role: str
    content: str


class ReviseRequest(BaseModel):
    messages: list[ReviseMessage]


class EditScreenplayRequest(BaseModel):
    screenplay: str


class RevertRequest(BaseModel):
    version_index: int


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
    # 把入口模式钉在开拍这一刻:此后剧本产出会让"当前有没有正文"翻转,
    # 而左栏步骤清单必须整集恒定(见 episode_service.entry_mode)。
    ep.entry_mode_at_start = episode_service.entry_mode(
        ep, await _script_content(db, ep.script_id))
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

    graph = await get_graph()
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
        "cast": req.cast,
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


async def _graph_still_paused(episode_id: str) -> bool | None:
    """图是否仍停在某个中断点。True=在暂停、False=确认没有状态、None=无法判断(不下结论)。

    投影里的 paused_at 是"当初暂停时"的如实记录,但图状态可能已经不在了
    (checkpoint 文件被换/删、跑该集的是已消失的旧进程实例)。此时投影仍说"待审核",
    前端照样渲染出可点的审核面板,用户点下去才被 resume/revise 的守卫拒掉 —— 那两个
    守卫读的是活图,是对的;错在 status 从不校验自己下发的暂停点还作不作数。

    **只在图单例已初始化时才读**:get_graph() 会惰性建一条 aiosqlite 连接,而它的工作
    线程是非 daemon 的、必须由 lifespan 的 close_graphs() 收(原因见 graph.py:282-292)。
    status 是前端轮询接口,不能由它来建这条连接 —— 那正是今天堆出一批僵尸进程的成因。
    图没初始化时返回 None(无法判断),不据此宣告状态丢失。
    """
    from drama_agent.workflow import graph as graph_mod
    if graph_mod._graph is None:      # 未初始化:不在此处建连,交由 lifespan 负责
        return None
    try:
        state = await graph_mod._graph.aget_state(
            {"configurable": {"thread_id": episode_id}})
    except Exception:  # noqa: BLE001 — 图不可读是暂时故障,不下"已丢失"的结论
        return None
    return bool(state and getattr(state, "next", ()))


async def _script_content(db: AsyncSession, script_id: str | None) -> str | None:
    """源剧本正文(供入口模式判定);取不到按无正文处理。"""
    if not script_id:
        return None
    from drama_agent.db.models import Script
    row = (await db.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    return row.content if row else None


@router.get("/{episode_id}/workflow/status")
async def get_workflow_status(episode_id: str, db: AsyncSession = Depends(get_db)):
    """轻量状态:读投影(Episode 生命周期 + 最近事件摘要),不反序列化整个图状态。

    仅当投影声称"暂停中"时才额外核对一次暂停点是否还在 —— 那是唯一会让用户对着
    不存在的状态做操作的情形,值得这一次读;其余路径仍然只读投影。
    """
    ep = await _get_episode_or_404(db, episode_id)
    snapshot = ep.state_snapshot or {}
    current_stage = snapshot.get("current_stage")
    paused_at = snapshot.get("paused_at")
    # 暂停点核对:图确认没有状态 → 这个 paused_at 已经作不了数,不能再下发成可操作的审核态
    state_lost = False
    if paused_at:
        still = await _graph_still_paused(episode_id)
        if still is False:
            state_lost = True
            paused_at = None
    agg = await cost_service.aggregate_entity(db, episode_id)
    shots = snapshot.get("shots", [])
    script_content = await _script_content(db, ep.script_id)
    return {
        "episode_id": episode_id,
        "project_id": ep.project_id,
        "db_status": ep.status,
        "current_stage": current_stage,
        "paused_at": paused_at,
        # 投影说暂停、图里却没有状态 —— 该集无法继续,只能重置重跑。
        # 前端据此提示,而不是给一个点下去必然 409 的审核面板。
        "state_lost": state_lost,
        "shots": shots,
        # 真实成片时长 = 各镜头时长之和,后端算好下发(唯一真相)。
        # 剧本正文里那种"时长：约8-10分钟"是 LLM 编的,不可作为时长来源。
        "total_duration_seconds": sum(int(s.get("duration_seconds") or 0) for s in shots),
        "prompts": snapshot.get("prompts", []),
        "videos": snapshot.get("videos", []),
        "assembled_video_path": snapshot.get("assembled_video_path"),
        "story_analysis": snapshot.get("story_analysis"),
        "screenplay": snapshot.get("screenplay"),
        "look_assignments": snapshot.get("look_assignments", {}),
        "cast": snapshot.get("cast", {}),
        # 待确认的角色身份(cast_review 中断时由节点算好放进图状态的 interrupt 载荷,
        # 快照里取不到时前端按空处理 —— 面板只在真有待确认项时才有内容)
        "cast_pending": snapshot.get("cast_pending", []),
        # 剧本版本树在 Episode 专用列(非 snapshot,见 Task 4):剧集页审核面板据此渲染版本下拉。
        "screenplay_versions": ep.screenplay_versions or [],
        "screenplay_version_current": ep.screenplay_version_current,
        # 分镜版本树(同上,实体是 shots):分镜审核面板据此渲染版本下拉/回退。
        "shots_versions": ep.shots_versions or [],
        "shots_version_current": ep.shots_version_current,
        # 分镜总时长压到每镜下限仍超集级目标 → 前端提示"退回重新生成"(单一真相在后端收敛逻辑)
        "duration_over_target": bool(snapshot.get("duration_over_target", False)),
        # 流水线步骤(单一真相在后端 pipeline_steps);中断时以 paused_at 作当前步。
        # by_node 的键是 current_stage,由 build_pipeline 按 stages 归并到步上。
        # 入口模式的唯一权威在 episode_service.entry_mode(规范 4):判据是有没有正文。
        # 只看 script_id 会把"从故事新建"的集(剧本正文还空)判成 from_script,
        # 于是前端隐掉它实际要跑的剧本三步。
        "pipeline": build_pipeline(
            episode_service.entry_mode(ep, script_content),
            ep.use_keyframes, paused_at or current_stage, costs=agg["by_node"]
        ),
        "cost_total": agg["total"],
        "cost_unpriced": agg["unpriced"],
        "cost_tokens_total": agg["tokens_total"],
        "cost_by_kind": agg["by_kind"],
        "error_message": ep.error_message,
        # 事件水位:前端拿它作 WebSocket 的 last_seq 起点。不下发的话前端只能从 0 起,
        # 后端就把该集**全部历史事件**当增量补给它 —— 早已修掉的旧 error 会在每次
        # 刷新时被重新弹成 toast(实测:页面反复报一个已经不存在的错误)。
        "last_seq": await event_service.latest_seq(db, episode_id),
    }


@router.get("/{episode_id}/workflow/state")
async def get_workflow_state(episode_id: str, db: AsyncSession = Depends(get_db)):
    """完整状态:从 checkpointer 读图(重操作,仅在需要完整 state 时用)。"""
    await _get_episode_or_404(db, episode_id)
    graph = await get_graph()
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
        "cast": full.get("cast", {}),
        "cast_pending": full.get("cast_pending", []),
        "references": reference_service.build_list(full),
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


# ── 剧本审核(剧集页):AI 改写 / 手动编辑 / 版本回退 ────────────────────
# 从原 api/scripts.py 搬来,守卫从"剧本图停在 screenplay_review"改为"统一图停在此",
# 实体从 Script 换成 Episode(裁决 A/B,见 SDD ledger)。

async def _require_paused_screenplay_review(episode_id: str, db: AsyncSession):
    """审核态三端点共用守卫:集存在 + 统一图暂停在 screenplay_review。
    返回 (ep, graph, config, current_screenplay);不满足直接抛 HTTPException。"""
    ep = await _get_episode_or_404(db, episode_id)
    graph = await get_graph()
    config = {"configurable": {"thread_id": episode_id}}
    state = await graph.aget_state(config)
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if "screenplay_review" not in next_nodes:
        raise HTTPException(status_code=409, detail="剧本当前不处于待审核状态，无法改写")
    current = (getattr(state, "values", None) or {}).get("screenplay")
    return ep, graph, config, current


@router.post("/{episode_id}/screenplay/revise")
async def revise_screenplay(
    episode_id: str, req: ReviseRequest, db: AsyncSession = Depends(get_db)
):
    """对话式改写:确认-执行 agent 单轮决策。action=ask 只回复;action=apply 追加版本 + 写回图。"""
    ep, graph, config, current = await _require_paused_screenplay_review(episode_id, db)
    model = ep.llm_model or ""
    if not model:
        default_model = provider_pkg.provider_registry.effective_default("llm")
        model = default_model.id if default_model else ""
    if not model:
        raise HTTPException(status_code=500, detail="未配置可用的文本模型，请先到「模型管理」配置")

    # 同一个改写 agent 服务原文与剧本(见 text_revise_service);此处的落库出口是
    # 版本树 + 图状态,那是**这个调用方**的事,agent 对写哪儿零感知。
    result = await text_revise_service.turn(
        text_revise_service.TextKind.SCREENPLAY,
        current or "", [m.model_dump() for m in req.messages], model,
    )
    if result["action"] != "apply":
        return {"action": "ask", "reply": result["reply"]}

    version = await episode_service.append_screenplay_version(
        db, episode_id, new_screenplay=result["text"], seed_screenplay=current or "",
        label=result["summary"] or "AI 改写",
    )
    if version is None:                       # 守卫已确认集存在,理论到不了;防御性 404
        raise HTTPException(status_code=404, detail="Episode not found")
    await graph.aupdate_state(config, {"screenplay": result["text"]})
    return {
        "action": "apply", "reply": result["reply"], "screenplay": result["text"],
        "version_index": version["version_index"], "versions_len": version["versions_len"],
    }


@router.post("/{episode_id}/screenplay/edit")
async def edit_screenplay(
    episode_id: str, req: EditScreenplayRequest, db: AsyncSession = Depends(get_db)
):
    """手动编辑剧本全文:落一个新版本(label「手动编辑」)+ 写回图。
    先过状态守卫(404/409)再校验正文非空(422)——资源状态先于请求体校验。"""
    _ep, graph, config, current = await _require_paused_screenplay_review(episode_id, db)
    if not req.screenplay.strip():
        raise HTTPException(status_code=422, detail="剧本正文不能为空")
    version = await episode_service.append_screenplay_version(
        db, episode_id, new_screenplay=req.screenplay, seed_screenplay=current or "",
        label="手动编辑",
    )
    if version is None:                       # 守卫已确认集存在,理论到不了;防御性 404
        raise HTTPException(status_code=404, detail="Episode not found")
    await graph.aupdate_state(config, {"screenplay": req.screenplay})
    return {"screenplay": req.screenplay, "version_index": version["version_index"]}


@router.post("/{episode_id}/screenplay/revert")
async def revert_screenplay(
    episode_id: str, req: RevertRequest, db: AsyncSession = Depends(get_db)
):
    """回退到历史版本:切换 current + 写回图。"""
    _ep, graph, config, _current = await _require_paused_screenplay_review(episode_id, db)
    try:
        version = await episode_service.set_current_version(db, episode_id, req.version_index)
    except IndexError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if version is None:                       # 守卫已确认集存在,理论到不了;防御性 404
        raise HTTPException(status_code=404, detail="Episode not found")
    await graph.aupdate_state(config, {"screenplay": version["screenplay"]})
    return version


# ── 分镜版本树(与上面剧本审核三端点同构,实体字段换成 shots) ───────────────

async def _require_paused_storyboard_review(episode_id: str, db: AsyncSession):
    """守卫:集存在 + 统一图暂停在 storyboard_review。返回 (ep, graph, config)。"""
    ep = await _get_episode_or_404(db, episode_id)
    graph = await get_graph()
    config = {"configurable": {"thread_id": episode_id}}
    state = await graph.aget_state(config)
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if "storyboard_review" not in next_nodes:
        raise HTTPException(status_code=409, detail="分镜当前不处于待审核状态，无法回退版本")
    return ep, graph, config


class RevertShotsRequest(BaseModel):
    version_index: int


@router.post("/{episode_id}/storyboard/revert")
async def revert_storyboard(
    episode_id: str, req: RevertShotsRequest, db: AsyncSession = Depends(get_db)
):
    """回退到历史分镜版本:切换 current + 写回图状态(shots)。"""
    _ep, graph, config = await _require_paused_storyboard_review(episode_id, db)
    try:
        version = await episode_service.set_current_shots_version(db, episode_id, req.version_index)
    except IndexError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if version is None:                       # 守卫已确认集存在,理论到不了;防御性 404
        raise HTTPException(status_code=404, detail="Episode not found")
    await graph.aupdate_state(config, {"shots": version["shots"]})
    return version
