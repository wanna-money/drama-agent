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

# Module-level singletons — initialized once at app startup via init_graphs()
_script_graph = None
_video_graph = None


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


async def screenplay_revision_node(state: DramaState) -> dict:
    """Re-write screenplay based on revision notes."""
    from drama_agent.services.llm_service import llm_service
    revised = await llm_service.complete(
        "You are a professional screenplay writer. Revise the screenplay based on the feedback.",
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


def route_after_screenplay_review_script(state: DramaState) -> str:
    return END if state["screenplay_approved"] else "screenplay_revision"


def route_after_look_review(state: DramaState) -> str:
    return "prompt_engineer" if state["look_assignments_approved"] else "look_assignment"


def route_after_prompts_review(state: DramaState) -> str:
    if not state["prompts_approved"]:
        return "prompt_engineer"
    return "keyframe_generator" if state.get("use_keyframes") else "video_generator"


def route_after_keyframes_review(state: DramaState) -> str:
    return "video_generator" if state["keyframes_approved"] else "keyframe_generator"


def build_script_graph(checkpointer):
    """写作图:故事 → 剧本 → 审核(approved 即结束)。"""
    b = StateGraph(DramaState)
    b.add_node("story_analyzer", story_analyzer_node)
    b.add_node("screenplay_writer", screenplay_writer_node)
    b.add_node("screenplay_review", screenplay_review_node)
    b.add_node("screenplay_revision", screenplay_revision_node)
    b.add_edge(START, "story_analyzer")
    b.add_edge("story_analyzer", "screenplay_writer")
    b.add_edge("screenplay_writer", "screenplay_review")
    b.add_conditional_edges(
        "screenplay_review",
        route_after_screenplay_review_script,
        {END: END, "screenplay_revision": "screenplay_revision"},
    )
    b.add_edge("screenplay_revision", "screenplay_review")
    return b.compile(checkpointer=checkpointer)


def build_video_graph(checkpointer):
    """拍摄图:分镜 → look → prompt → 关键帧 → 视频 → 合成。"""
    b = StateGraph(DramaState)
    for name, fn in [
        ("storyboard_director", storyboard_director_node),
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
    b.add_edge(START, "storyboard_director")
    b.add_edge("storyboard_director", "look_assignment")
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
    """Initialize both graph singletons on a shared checkpointer. Call once at startup."""
    global _script_graph, _video_graph
    import aiosqlite
    import os
    os.makedirs(os.path.dirname(os.path.abspath(settings.langgraph_db_path)), exist_ok=True)
    conn = await aiosqlite.connect(settings.langgraph_db_path)
    checkpointer = AsyncSqliteSaver(conn)
    _script_graph = build_script_graph(checkpointer)
    _video_graph = build_video_graph(checkpointer)


async def get_script_graph():
    """Return the singleton script (writing) graph, initializing if necessary."""
    global _script_graph
    if _script_graph is None:
        await init_graphs()
    return _script_graph


async def get_video_graph():
    """Return the singleton video (shooting) graph, initializing if necessary."""
    global _video_graph
    if _video_graph is None:
        await init_graphs()
    return _video_graph
