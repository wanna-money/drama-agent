"""工作流执行核心:在统一制作图上跑一集,thread_id = episode_id。

图内部按"是否已有通过的剧本"分流(有 → 直达分镜;无 → 从故事分析开始),
故此处不再按 job.kind 挑图。状态变更 + 事件同事务写(S2)。调度在 worker,不在此。
"""
from langgraph.types import Command
from sqlalchemy import select
from drama_agent.db import session as db_session
from drama_agent.db.models import Episode, Script, Project
from drama_agent.db.enums import (
    LifecycleStatus, JobKind, EventType, Genre, AdaptationStatus, VisualStyle,
)
from drama_agent.services import (
    episode_service, event_service, reference_service, story_service,
)
from drama_agent.workflow.graph import get_graph
from drama_agent.workflow.usage_context import set_usage_context
import structlog

logger = structlog.get_logger()

RESUME_KINDS = {JobKind.RESUME.value}

# 人工审核卡点的节点名(与 graph.py 注册的节点一一对应)。这些节点**只 interrupt**,
# 不会"抛异常卡住",故图停在它们上面时一定是在等审核决策 —— 必须发 Command(resume)。
REVIEW_NODES = frozenset({
    "cast_review", "screenplay_review", "storyboard_review",
    "look_review", "prompts_review", "keyframes_review",
})


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


def _is_empty_projection(payload: dict) -> bool:
    """这份投影是不是"空状态"(图以空 dict 起跑时产出的样子)。

    判据是**内容全空**:没有剧本、没有分镜、没有 prompts、没有阶段名。正常运行的第一个
    事件至少带 current_stage,故不会被误判。
    """
    if payload.get("current_stage"):
        return False
    return not any(payload.get(k) for k in
                   ("screenplay", "shots", "prompts", "videos", "story_analysis"))


async def _persist(
    entity_id: str, project_id: str,
    status: LifecycleStatus, event_type: EventType, payload: dict,
) -> None:
    """写 Episode status+snapshot + 事件同事务。

    **空投影不覆盖已有快照**:_persist 是整表覆盖,而一次"空状态重跑"(如对着已消费的
    中断重发 resume)会边跑边把全 null 的投影写进去,再在某个节点失败 —— 于是图状态完好、
    投影却被毁掉:status 读到 shots=0、审核面板消失,用户看到"卡住"而无路可走(实测)。
    事件照记(它是事实,便于追溯),但不拿空值污染快照。
    """
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Episode).where(Episode.id == entity_id)
        )).scalar_one_or_none()
        if row:
            row.status = status.value
            # 写入任一非失败态就是"当前不是失败"的声明,故清掉上一轮的错误。
            # 不清的话它永久残留:装好 ffmpeg 重跑成功、成片都在了,界面仍显示
            # 「工作流错误: [Errno 2] ...」,用户无法判断这一集到底成没成(实测)。
            # FAILED 态则相反:payload["error"] 是本次失败的原因,必须落到这一列,
            # 否则界面只会显示"失败"而不知道为什么。
            row.error_message = payload.get("error") if status == LifecycleStatus.FAILED else None
            if not (_is_empty_projection(payload) and row.state_snapshot):
                row.state_snapshot = payload
            await db.flush()
        await event_service.append_event(db, entity_id, event_type, payload, project_id=project_id)


async def _mark_status_only(
    entity_id: str, project_id: str,
    status: LifecycleStatus, event_type: EventType, paused_at: str | None,
) -> None:
    """只改 status + 记一条事件,保持 state_snapshot 原样。

    用于"解开状态死锁"这类修正:此时图与投影可能不一致(投影才是接口下发的真相),
    顺手覆盖快照会把已有产出改少。
    """
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Episode).where(Episode.id == entity_id)
        )).scalar_one_or_none()
        if row:
            row.status = status.value
            row.error_message = None    # 同 _persist:回正到非失败态即清旧错误
            await db.flush()
        payload = {"lifecycle": status.value}
        if paused_at:
            payload["paused_at"] = paused_at
        await event_service.append_event(db, entity_id, event_type, payload,
                                         project_id=project_id)


async def run_job(job: dict) -> None:
    # 作品级改编:adapt job 的 episode_id 列载的是 project_id(见 db/enums.JobKind.ADAPT)
    if job["kind"] == JobKind.ADAPT.value:
        await _run_adaptation(job["episode_id"])
        return
    # 散片直接生成:clip job 的 episode_id 列载的是 clip_id(见 db/enums.JobKind.CLIP)。
    # 不加这个早退,新 kind 会掉进下方 _build_initial_state —— 它按 episode_id 查 Episode,
    # 查不到直接抛。
    if job["kind"] == JobKind.CLIP.value:
        from drama_agent.workflow import clip_runner
        await clip_runner.run_clip(job["episode_id"])
        return
    episode_id = job["episode_id"]
    project_id = job.get("project_id", "")
    graph = await get_graph()
    config = {"configurable": {"thread_id": episode_id}}

    # None 是 LangGraph 的"继续执行 pending 任务"输入(见下方 resume 分支)
    stream_input: Command | dict | None
    if job["kind"] in RESUME_KINDS:
        # resume 必须先确认图**真的停在中断点**(规范 3:写接口幂等)。
        # LangGraph 对着没有 pending interrupt 的 thread 收到 Command(resume=...) 时
        # 不报错,而是丢掉 resume 值、从 START 重跑一遍 —— 空状态进 story_analyzer
        # 就是 KeyError: 'project_id'。这条路径在重试时必然发生:第一次 resume 消费掉
        # 中断,worker 因任何原因重试同一 job,第二次就走进"重跑"，而它的报错还会
        # 盖掉第一次的真实失败原因(实测过,排查了很久)。
        state = await graph.aget_state(config)
        # 判据是 **interrupts**(由 checkpoint 的 pending INTERRUPT 写入导出),不是 next:
        # LangGraph 靠 pending writes 里的 INTERRUPT 把 resume 值挂到具体 task 上
        # (见 _loop.py 的 _pending_interrupts / map_command)。那批 pending writes 一旦
        # 不在,resume 就变成 NULL_TASK_ID 写入 → 从 START 重跑。
        # 而 next 只表示"下一步该跑谁",图停在中断点时它非空、pending writes 却可能已没了
        # —— 只看 next 会放行一次注定从头重跑的 resume(实测:图里 14 个镜头完好,
        # 却跑出一串全 null 的事件并以 KeyError 收场)。
        next_nodes = tuple(getattr(state, "next", ()) or ()) if state else ()
        has_interrupt = bool(state and getattr(state, "interrupts", ()))
        # 停在审核卡点时**一律**发 Command:interrupts 读到空有两种可能 ——
        #   (a) 中断真的没了(某节点抛异常卡住)→ 该用 None 驱动;
        #   (b) pending writes 尚未落盘 / 读取时机不巧 → 仍是审核卡点。
        # 两者在 next 上可分:审核节点只 interrupt、不会"抛异常卡住",故停在它上面必是 (b)。
        # 不分开会把 approved/notes 丢掉 —— 该审核节点被重跑并再次中断,
        # 用户点了「通过」等于没点(实测:分镜点通过后仍停在原处)。
        at_review = bool(next_nodes) and next_nodes[0] in REVIEW_NODES
        if has_interrupt or at_review:
            stream_input = Command(resume=job.get("payload_json") or {})
        elif next_nodes:
            # 停在一个**非中断**节点上(如某节点抛异常后重试耗尽):没有 pending interrupt,
            # 却也没跑完。此时 start 被"已启动"守卫拒、Command(resume) 会丢掉 resume 值
            # 从 START 重跑 —— 只有 None 输入能继续执行那个 pending 任务。
            # 不这么做,这一集在界面上没有任何入口能重试它。
            logger.info("resume: 图停在非中断节点,以 None 输入驱动其继续",
                        episode_id=episode_id, job_id=job.get("id"), next_nodes=next_nodes)
            stream_input = None
        else:
            # 图确已跑完:没有任何 pending 任务可驱动,只把 status 从 queued 回正。
            # 入队时置的 queued 若留在库里,start 与 resume 都会被拒 —— 界面上再无入口
            # 可解这一集(实测)。**只改 status 不动 state_snapshot**:此处职责是解死锁,
            # 顺手用图 values 覆盖快照会在两者不一致时把已有产出改少。
            logger.info("resume skipped: 图已跑完且无中断,回正状态",
                        episode_id=episode_id, job_id=job.get("id"))
            await _mark_status_only(episode_id, project_id, LifecycleStatus.COMPLETED,
                                    EventType.COMPLETED, None)
            return
    else:
        stream_input = await _build_initial_state(episode_id)

    # 首个事件在第一个节点跑完后才到,故先置一次归属;随后每事件按 current_stage 刷新。
    set_usage_context(entity_id=episode_id, project_id=project_id, is_script=False, node="")

    # durability="sync":每步 checkpoint **落盘后**才继续。
    # LangGraph 默认 "async" —— 写入异步排队,不保证 astream 返回前已落盘。于是
    # astream 结束后紧接着 aget_state 常读到空:投影说 paused、图里却没有状态,
    # status 判 state_lost、审核面板消失,这一集只能重置重跑(实测时好时坏,
    # 因为它取决于写入是否恰好赶上)。
    # 本项目每个卡点都要人工审核后 resume,状态必须真的在库里 —— 这点性能换正确性。
    async for event in graph.astream(stream_input, config=config, stream_mode="values",
                                     durability="sync"):
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
        # 终态不能只看图拓扑:图正常跑到尾 ≠ 产出可用。装配节点在无可用视频时
        # 明确回了 error,若仍落 COMPLETED,一集全部失败也会显示"已完成",
        # 且 error_message 被 _persist 覆盖成 None —— 用户只能逐条点开 videos
        # 才知道真相。
        err = values.get("error")
        vids = values.get("videos") or []
        all_failed = bool(vids) and not any(v.get("status") == "succeeded" for v in vids)
        if err or all_failed:
            payload = _summary(values)
            payload["error"] = err or "所有镜头生成失败"
            await _persist(episode_id, project_id, LifecycleStatus.FAILED,
                           EventType.ERROR, payload)
        else:
            await _persist(episode_id, project_id, LifecycleStatus.COMPLETED,
                           EventType.COMPLETED, _summary(values))


async def _run_adaptation(project_id: str) -> None:
    """作品级改编,分两阶段(同一个 job kind,按当前状态决定这次跑哪一阶段):

      1) 抽整本小说的角色 → 有待确认项则停在 cast_review 等人工
      2) 角色已定(adapting)→ 切分成 N 个剧本

    分两阶段是因为角色必须在切分**之前**确立:切分后各段自行发明称呼,同一角色跨集
    就成了不同名字,下游按 character_id 取造型必然落空。人工确认后由 /confirm-cast
    重新入队本 job,走到第 2 阶段。

    产出不可用由 adapt 内部落 failed;传输层异常在此先标 failed 再抛(交 job 重试),
    否则作品会永远停在中间态。
    """
    from drama_agent.db.enums import AdaptationStatus
    from drama_agent.services import adaptation_service
    async with db_session.AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if row is None:
            return
        stage = row.adaptation_status
    async with db_session.AsyncSessionLocal() as db:
        try:
            if stage != AdaptationStatus.ADAPTING.value:
                # 尚未确立角色:先抽角色。有待确认项就停在 cast_review,不继续切分。
                result = await adaptation_service.analyze_cast(db, project_id)
                payload = {"adaptation_status": result["adaptation_status"],
                           "cast_pending": len(result["pending"])}
                if result["adaptation_status"] == AdaptationStatus.CAST_REVIEW.value:
                    await event_service.append_event(
                        db, project_id, EventType.STAGE_CHANGE, payload,
                        project_id=project_id)
                    return
            result = await adaptation_service.adapt(db, project_id)
            payload = {"adaptation_status": result["adaptation_status"],
                       "scripts": len(result["scripts"])}
        except Exception:
            await _mark_adaptation_failed(project_id)
            raise
        await event_service.append_event(
            db, project_id, EventType.STAGE_CHANGE, payload, project_id=project_id)


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
    """本集的图初始状态。

    分流判据是**有没有正文**,不是有没有起始方案:方案存在而正文为空时仍要跑剧本步
    (正文正是流水线要产出的东西)。按"有 script_id 就算已通过"分流,会让这类集
    带着空剧本直达分镜。
      · 有正文(改编切片种入版本 / 复用已写好的方案)→ screenplay_approved=True,直达分镜
      · 只有原文 → approved=False,由 story_analyzer 起跑
    判据必须与 graph.route_entry 一致 —— 那边只看 screenplay_approved。
    """
    async with db_session.AsyncSessionLocal() as db:
        ep = (await db.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
        sc = None
        if ep.script_id:
            sc = (await db.execute(
                select(Script).where(Script.id == ep.script_id)
            )).scalar_one_or_none()
        # 原文是集的锚点,直接经 ep.story_id 取 —— 不绕 Script:
        # 从故事开跑的集没有 script_id,绕过去就取不到原文(而它正是第一步的输入)。
        story = await story_service.row_of(db, ep.story_id or "")
        # 开拍前绑好的参考图带进图状态;reference_service 负责兼容旧 character_references 快照
        existing_refs = reference_service.stored(ep.state_snapshot)
        seeded = episode_service.seeded_screenplay(ep)
        if seeded:                                     # 改编切片(建集时种入)
            screenplay, analysis = seeded, None
        else:
            screenplay = (sc.content if sc else "") or ""
            analysis = story.story_analysis if story else None
        # 与 status 端点同源(规范 4);那边据同一判据决定要不要展示剧本三步
        approved = episode_service.entry_mode(ep, sc.content if sc else None) == "from_script"
        genre = analysis.get("genre") if isinstance(analysis, dict) else None
        # 四跳链:analysis(分析节点回显)→ story(建原文时的类型)→ project(建作品时
        # 用户显式选的那个)→ sc(改编方案落的值)→ 兜底 drama。
        # 从故事开跑的集没有 Script、首跑没有 analysis;而**建集表单上没有类型选择器**
        # (类型是建作品时选的)—— 缺 story/project 这两跳时必然落到 drama,
        # 用户在界面上选的类型永不生效,且没有任何报错。
        proj_row = (await db.execute(
            select(Project.genre, Project.visual_style)
            .where(Project.id == ep.project_id))).one_or_none()
        proj_genre = proj_row[0] if proj_row else None
        visual_style = proj_row[1] if proj_row else VisualStyle.REALISTIC.value
        genre = genre or (story.genre if story else None) or proj_genre \
            or (sc.genre if sc else None) or Genre.DRAMA.value
        return {
            "project_id": ep.project_id, "episode_id": episode_id,
            "episode_number": ep.episode_number, "title": ep.title,
            # 故事原文的家是 Story(集与 Script 都不存它)
            "raw_input": (story.content if story else "") or "",
            "story_id": ep.story_id, "script_id": ep.script_id,
            "genre": genre,
            "story_analysis": analysis, "screenplay": screenplay,
            "visual_style": visual_style,
            "screenplay_approved": approved,
            "screenplay_revision_notes": "",
            "shots": [], "target_seconds": ep.target_seconds,
            "storyboard_approved": False, "duration_over_target": False,
            "storyboard_revision_notes": "",
            "prompts": [], "prompts_approved": False,
            "prompt_revision_notes": "", "videos": [], "references": existing_refs,
            # 剧本入库时已确认的阵容随集进图:图内 cast_review 只在这里为空时才需要问
            # (身份确认应当只发生一次 —— 剧本入库那一次)
            "cast": (story.cast if story and story.cast else {}), "cast_pending": [],
            "current_stage": "storyboard_start" if approved else "starting",
            "error": None,
            "llm_model": ep.llm_model or _fallback_llm_model(),
            "video_model": ep.video_model,
            "video_provider": ep.video_provider, "resolution": ep.resolution,
            "aspect_ratio": ep.aspect_ratio,
            "use_keyframes": ep.use_keyframes, "keyframe_image_model": ep.keyframe_image_model,
            "keyframes_approved": False, "look_assignments": {},
            "look_assignments_approved": False, "assembled_video_path": None,
        }
