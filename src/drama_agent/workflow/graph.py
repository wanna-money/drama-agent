from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
except ImportError:
    from langgraph_checkpoint_sqlite import AsyncSqliteSaver  # type: ignore
from drama_agent.workflow.state import DramaState
from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
from drama_agent.workflow.nodes.screenplay_writer import screenplay_writer_node
from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node
from drama_agent.workflow.nodes.look_assignment import look_assignment_node
from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node
from drama_agent.workflow.nodes.keyframe_generator import keyframe_generator_node
from drama_agent.workflow.nodes.video_generator import video_generator_node
from drama_agent.workflow.nodes.video_assembler import video_assembler_node
from drama_agent.config import settings

# Module-level singleton — initialized once at app startup via init_graphs()
_graph = None
# 图所用的 aiosqlite 连接。单独留一份引用是为了能在进程退出前显式关掉它 ——
# 它的工作线程是非 daemon 的,不关就退不出进程(详见 close_graphs)。
_checkpointer_conn = None


async def screenplay_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: pause for screenplay approval."""
    decision = interrupt({
        "stage": "screenplay_review",
        "screenplay": state["screenplay"],
        "title": state["title"],
    })
    approved = decision.get("approved", False)
    notes = decision.get("notes", "")
    if not approved:
        return {
            "screenplay_approved": False,
            "screenplay_revision_notes": notes,
            "current_stage": "screenplay_revision_requested",
        }
    return {
        "screenplay_approved": True,
        "screenplay_revision_notes": "",
        "current_stage": "screenplay_approved",
    }


async def cast_resolve_node(state: DramaState) -> dict:
    """把剧本人物对齐到作品角色库,产出 cast 与待确认清单。

    与 cast_review 分成两个节点(照 look_assignment → look_review 的先例):interrupt()
    会挂起节点,其后的 return 只在 resume 时才执行 —— 待确认清单必须在**中断之前**就
    写进状态,否则前端读 status 投影时拿不到"要确认什么"。
    """
    from drama_agent.services import cast_service
    resolved = await cast_service.resolve(state["project_id"], state.get("story_analysis"))
    return {
        "cast": resolved["cast"],
        "cast_pending": resolved["pending"],
        "current_stage": "cast_resolved",
    }


async def cast_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: 确认剧本人物 → 作品角色的身份对应。

    放在写剧本**之前**:确认后剧本正文直接用规范名,下游(分镜角色名/造型/音色)
    全部自然对齐,不需要事后改名回写正文。

    无待确认项时(全部同名命中,或角色库读不到)**不得中断**:前端只在 cast_pending
    非空时渲染确认面板,空清单中断会把本集停在一个没有 resume 入口的状态上。
    """
    from drama_agent.services import cast_service
    pending = state.get("cast_pending") or []
    if not pending:
        return {"cast_pending": [], "current_stage": "cast_confirmed"}
    decision = interrupt({
        "stage": "cast_review",
        "pending": pending,
        "cast": state.get("cast", {}),
    })
    cast = await cast_service.apply_decisions(
        state["project_id"], state.get("story_analysis"),
        decision.get("cast"), state.get("cast", {}))
    return {"cast": cast, "cast_pending": [], "current_stage": "cast_confirmed"}


def route_entry(state: DramaState) -> str:
    """条件入口:已有通过的剧本(复用剧本 or 改编切片)→ 直达分镜;否则从故事分析开始。"""
    return "storyboard_director" if state.get("screenplay_approved") else "story_analyzer"


async def screenplay_revision_node(state: DramaState) -> dict:
    """Re-write screenplay based on revision notes."""
    from drama_agent.services.llm_service import llm_service
    from drama_agent.workflow.prompt_rules import system_prompt
    revised = await llm_service.complete(
        # 走共享输出规则:漏掉它会让一次"退回修改"把已通过的中文剧本改成英文,再喂给分镜
        system_prompt(
            "You are a professional screenplay writer. "
            "Revise the screenplay based on the feedback."
        ),
        f"Original screenplay:\n{state['screenplay']}\n\nRevision notes:\n{state['screenplay_revision_notes']}\n\nWrite the revised screenplay:",
        temperature=0.7,
        model=state.get("llm_model"),
    )
    return {"screenplay": revised, "screenplay_approved": False, "current_stage": "screenplay_written"}


async def prompts_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: pause for prompt approval."""
    decision = interrupt({
        "stage": "prompts_review",
        "prompts": state["prompts"],
        "shots": state["shots"],
    })
    approved = decision.get("approved", False)
    edited_prompts = decision.get("edited_prompts", {})  # shot_id -> edited text
    edited_negative_prompts = decision.get("edited_negative_prompts", {})  # shot_id → negative text
    notes = decision.get("notes", "")

    if approved:
        # Apply any individual edits
        updated_prompts = []
        for p in state["prompts"]:
            updated = {**p, "approved": True}
            if p["shot_id"] in edited_prompts:
                updated["edited_prompt"] = edited_prompts[p["shot_id"]]
            if p["shot_id"] in edited_negative_prompts:
                updated["edited_negative_prompt"] = edited_negative_prompts[p["shot_id"]]
            updated_prompts.append(updated)
        return {
            "prompts": updated_prompts,
            "prompts_approved": True,
            "current_stage": "prompts_approved",
        }
    return {
        "prompts_approved": False,
        "prompt_revision_notes": notes,
        "current_stage": "prompts_revision_requested",
    }


async def look_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: 审核/编辑 场景→Look 指派。"""
    # 空指派(项目还没有角色实体 / 角色没入镜)时**不得中断**:UI 没有对应的 resume
    # 入口,中断会把本集停死在 look_review。视为"已确认"放行,留痕由 runner._summary
    # + _persist 的节点事件自然覆盖(节点状态即事件)。
    if not state["look_assignments"]:
        return {"look_assignments_approved": True, "current_stage": "looks_approved"}
    decision = interrupt({
        "stage": "look_review",
        "look_assignments": state["look_assignments"],
        "shots": state["shots"],
    })
    if decision.get("approved", False):
        edited = decision.get("assignments")
        result: dict = {"look_assignments_approved": True, "current_stage": "looks_approved"}
        if isinstance(edited, dict):
            result["look_assignments"] = edited
        return result
    edited = decision.get("assignments")
    result = {"look_assignments_approved": False, "current_stage": "looks_revision_requested"}
    if isinstance(edited, dict):
        result["look_assignments"] = edited
    return result


async def storyboard_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: 审核分镜(时长超目标或整体不满意时打回重做)。"""
    decision = interrupt({
        "stage": "storyboard_review",
        "shots": state["shots"],
        "duration_over_target": state.get("duration_over_target", False),
    })
    approved = decision.get("approved", False)
    notes = decision.get("notes", "")
    return {
        "storyboard_approved": approved,
        # 通过时清空历史打回意见,避免下一轮重生成残留上一次批注
        "storyboard_revision_notes": "" if approved else notes,
        "current_stage": "storyboard_approved" if approved else "storyboard_revision_requested",
    }


async def keyframes_review_node(state: DramaState) -> dict:
    """Human-in-the-loop: 审核关键帧,可逐镜重生成。"""
    decision = interrupt({
        "stage": "keyframes_review",
        "prompts": state["prompts"],
        "shots": state["shots"],
    })
    if decision.get("approved", False):
        return {"keyframes_approved": True, "current_stage": "keyframes_approved"}
    regenerate = set(decision.get("regenerate_shot_ids", []))
    # 打回但未指定任何镜头 → 视为"全部重生成"。否则 keyframe_generator 会因每镜都已有
    # keyframe_url 而全部跳过,原样再次 interrupt,形成无进展死循环(#9)。
    regen_all = not regenerate
    prompts = [
        {**p, "keyframe_url": None} if (regen_all or p["shot_id"] in regenerate) else p
        for p in state["prompts"]
    ]
    return {
        "prompts": prompts,
        "keyframes_approved": False,
        "current_stage": "keyframes_revision_requested",
    }


def route_after_screenplay_review(state: DramaState) -> str:
    """通过 → 进制作段(与"复用剧本"/"改编切片"两条入口会聚到同一个 storyboard_director);
    打回 → screenplay_revision 重写。"""
    return "storyboard_director" if state["screenplay_approved"] else "screenplay_revision"


def route_after_storyboard_review(state: DramaState) -> str:
    """通过 → 进造型指派;打回 → 回 storyboard_director 重新生成分镜。"""
    return "look_assignment" if state["storyboard_approved"] else "storyboard_director"


def route_after_look_review(state: DramaState) -> str:
    return "prompt_engineer" if state["look_assignments_approved"] else "look_assignment"


def route_after_prompts_review(state: DramaState) -> str:
    if not state["prompts_approved"]:
        return "prompt_engineer"
    return "keyframe_generator" if state.get("use_keyframes") else "video_generator"


def route_after_keyframes_review(state: DramaState) -> str:
    return "video_generator" if state["keyframes_approved"] else "keyframe_generator"


def build_unified_graph(checkpointer):
    """统一制作图:剧本创作与剧集制作一条线,条件入口分流。"""
    b = StateGraph(DramaState)
    for name, fn in [
        ("story_analyzer", story_analyzer_node),
        ("cast_resolve", cast_resolve_node),
        ("cast_review", cast_review_node),
        ("screenplay_writer", screenplay_writer_node),
        ("screenplay_review", screenplay_review_node),
        ("screenplay_revision", screenplay_revision_node),
        ("storyboard_director", storyboard_director_node),
        ("storyboard_review", storyboard_review_node),
        ("look_assignment", look_assignment_node),
        ("look_review", look_review_node),
        ("prompt_engineer", prompt_engineer_node),
        ("prompts_review", prompts_review_node),
        ("keyframe_generator", keyframe_generator_node),
        ("keyframes_review", keyframes_review_node),
        ("video_generator", video_generator_node),
        ("video_assembler", video_assembler_node),
    ]:
        b.add_node(name, fn)
    b.add_conditional_edges(
        START, route_entry,
        {
            "story_analyzer": "story_analyzer",
            "storyboard_director": "storyboard_director",
        },
    )
    # 剧本分支:分析 → 解析阵容 → 确认角色身份 → 写剧本
    # (确认在写之前,剧本才能直接用规范名;解析与确认分两节点见 cast_resolve_node 注释)
    b.add_edge("story_analyzer", "cast_resolve")
    b.add_edge("cast_resolve", "cast_review")
    b.add_edge("cast_review", "screenplay_writer")
    b.add_edge("screenplay_writer", "screenplay_review")
    b.add_conditional_edges(
        "screenplay_review",
        route_after_screenplay_review,
        {"storyboard_director": "storyboard_director", "screenplay_revision": "screenplay_revision"},
    )
    b.add_edge("screenplay_revision", "screenplay_review")
    # 制作分支(从 storyboard 起,两条入口都会聚到它)
    b.add_edge("storyboard_director", "storyboard_review")
    b.add_conditional_edges(
        "storyboard_review",
        route_after_storyboard_review,
        {"look_assignment": "look_assignment", "storyboard_director": "storyboard_director"},
    )
    b.add_edge("look_assignment", "look_review")
    b.add_conditional_edges(
        "look_review",
        route_after_look_review,
        {"prompt_engineer": "prompt_engineer", "look_assignment": "look_assignment"},
    )
    b.add_edge("prompt_engineer", "prompts_review")
    b.add_conditional_edges(
        "prompts_review",
        route_after_prompts_review,
        {
            "prompt_engineer": "prompt_engineer",
            "keyframe_generator": "keyframe_generator",
            "video_generator": "video_generator",
        },
    )
    b.add_edge("keyframe_generator", "keyframes_review")
    b.add_conditional_edges(
        "keyframes_review",
        route_after_keyframes_review,
        {"video_generator": "video_generator", "keyframe_generator": "keyframe_generator"},
    )
    b.add_edge("video_generator", "video_assembler")
    b.add_edge("video_assembler", END)
    return b.compile(checkpointer=checkpointer)


async def init_graphs():
    """Initialize the unified graph singleton on a shared checkpointer. Call once at startup.

    幂等:已初始化则直接返回 —— 重复建连会让旧连接失去引用者,而它的工作线程停不下来
    (原因见 close_graphs)。连接必须在进程退出前经 close_graphs() 关掉。
    """
    global _graph, _checkpointer_conn
    if _graph is not None:
        return
    import aiosqlite
    import os
    os.makedirs(os.path.dirname(os.path.abspath(settings.langgraph_db_path)), exist_ok=True)
    _checkpointer_conn = await aiosqlite.connect(settings.langgraph_db_path)
    checkpointer = AsyncSqliteSaver(_checkpointer_conn)
    _graph = build_unified_graph(checkpointer)


async def close_graphs():
    """关闭 checkpointer 连接并清空图单例。**进程退出前必须调用**,幂等。

    为什么非关不可:aiosqlite 的连接工作线程是**非 daemon** 线程。连接被本模块的图单例
    一直持有,永不被 GC,于是 Connection.__del__ 里那条兜底的 stop() 也永不执行 ——
    解释器退出时 threading._shutdown() 会永久 join 这条线程,进程再也退不出去:
      · pytest:整套跑完、结果都打印了却卡住不返回
      · uvicorn --reload:旧 server 子进程收不干净,继续占着 checkpoint db;
        多次重启后堆起一批僵尸,请求可能被事件循环已停的那个接走 → 后端整体无响应
    (事件循环已关闭的场景下不能 await close(),改用同步的 conn.stop();见 tests/conftest.py)
    """
    global _graph, _checkpointer_conn
    _graph = None
    conn, _checkpointer_conn = _checkpointer_conn, None
    if conn is not None:
        await conn.close()


async def get_graph():
    """Return the singleton unified graph, initializing if necessary."""
    global _graph
    if _graph is None:
        await init_graphs()
    return _graph
