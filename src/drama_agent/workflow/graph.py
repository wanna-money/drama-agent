from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
except ImportError:
    from langgraph_checkpoint_sqlite import AsyncSqliteSaver  # type: ignore
from drama_agent.workflow.state import DramaState
from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
from drama_agent.workflow.nodes.screenplay_writer import screenplay_writer_node
from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node
from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node
from drama_agent.workflow.nodes.video_generator import video_generator_node
from drama_agent.workflow.nodes.video_assembler import video_assembler_node
from drama_agent.config import settings

# Module-level singleton — initialized once at app startup via init_graph()
_graph = None


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
    notes = decision.get("notes", "")

    if approved:
        # Apply any individual edits
        updated_prompts = []
        for p in state["prompts"]:
            if p["shot_id"] in edited_prompts:
                updated_prompts.append({**p, "approved": True, "edited_prompt": edited_prompts[p["shot_id"]]})
            else:
                updated_prompts.append({**p, "approved": True})
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


def route_after_screenplay_review(state: DramaState) -> str:
    if state["screenplay_approved"]:
        return "storyboard_director"
    return "screenplay_revision"


def route_after_prompts_review(state: DramaState) -> str:
    if state["prompts_approved"]:
        return "video_generator"
    return "prompt_engineer"


def build_drama_graph(checkpointer):
    builder = StateGraph(DramaState)

    builder.add_node("story_analyzer", story_analyzer_node)
    builder.add_node("screenplay_writer", screenplay_writer_node)
    builder.add_node("screenplay_review", screenplay_review_node)
    builder.add_node("screenplay_revision", screenplay_revision_node)
    builder.add_node("storyboard_director", storyboard_director_node)
    builder.add_node("prompt_engineer", prompt_engineer_node)
    builder.add_node("prompts_review", prompts_review_node)
    builder.add_node("video_generator", video_generator_node)
    builder.add_node("video_assembler", video_assembler_node)

    builder.add_edge(START, "story_analyzer")
    builder.add_edge("story_analyzer", "screenplay_writer")
    builder.add_edge("screenplay_writer", "screenplay_review")
    builder.add_conditional_edges("screenplay_review", route_after_screenplay_review)
    builder.add_edge("screenplay_revision", "screenplay_review")
    builder.add_edge("storyboard_director", "prompt_engineer")
    builder.add_edge("prompt_engineer", "prompts_review")
    builder.add_conditional_edges("prompts_review", route_after_prompts_review)
    builder.add_edge("video_generator", "video_assembler")
    builder.add_edge("video_assembler", END)

    return builder.compile(checkpointer=checkpointer)


async def init_graph():
    """Initialize the module-level graph singleton. Call once at startup."""
    global _graph
    import aiosqlite
    import os
    os.makedirs(os.path.dirname(os.path.abspath(settings.langgraph_db_path)), exist_ok=True)
    conn = await aiosqlite.connect(settings.langgraph_db_path)
    checkpointer = AsyncSqliteSaver(conn)
    _graph = build_drama_graph(checkpointer)
    return _graph


async def get_graph():
    """Return the singleton graph, initializing it if necessary."""
    global _graph
    if _graph is None:
        await init_graph()
    return _graph
