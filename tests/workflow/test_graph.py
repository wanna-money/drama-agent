"""Integration test for the LangGraph workflow with mocked LLM and video."""
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
async def graph_with_mocks():
    """Build a real LangGraph with mocked LLM and video services."""
    import aiosqlite
    from drama_agent.workflow.graph import build_drama_graph
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError:
        from langgraph_checkpoint_sqlite import AsyncSqliteSaver

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = await aiosqlite.connect(db_path)
    checkpointer = AsyncSqliteSaver(conn)
    graph = build_drama_graph(checkpointer)

    yield graph

    await conn.close()
    os.unlink(db_path)


STORY_ANALYSIS = {
    "title": "Hero's Journey",
    "genre": "action",
    "setting": "Modern city",
    "themes": ["courage", "sacrifice"],
    "tone": "serious",
    "scene_count_estimate": 2,
    "plot_summary": "A hero saves the city.",
    "characters": [
        {"name": "Hero", "appearance": "Tall man in a red cape", "personality": "Brave", "reference_image_url": None}
    ],
}

SHOTS_DATA = [
    {
        "scene_number": 1, "shot_number": 1, "shot_type": "ELS",
        "camera_movement": "static", "duration_seconds": 5,
        "description": "City skyline", "characters": [],
        "action": "Establishing shot", "dialogue": "", "location": "EXT. CITY - DAY",
    }
]

PROMPT_DATA = {
    "prompt_text": "Epic city skyline, golden hour, cinematic",
    "negative_prompt": "blurry, low quality",
}


@pytest.mark.asyncio
async def test_graph_runs_to_screenplay_review(graph_with_mocks):
    """Verify the graph stops at screenplay_review interrupt."""
    from langgraph.types import Interrupt

    with patch("drama_agent.services.llm_service.llm_service.complete_json", new_callable=AsyncMock) as mock_cj, \
         patch("drama_agent.services.llm_service.llm_service.complete", new_callable=AsyncMock) as mock_c, \
         patch("drama_agent.services.rag_service.rag_service.save_character_profile") as mock_save, \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value=None):

        mock_cj.return_value = STORY_ANALYSIS
        mock_c.return_value = "INT. CITY - DAY\nHero stands tall.\n"

        config = {"configurable": {"thread_id": "test-project-1"}}
        initial_state = {
            "project_id": "test-project-1",
            "title": "Test",
            "raw_input": "A hero story",
            "genre": "action",
            "story_analysis": None,
            "screenplay": "",
            "screenplay_approved": False,
            "screenplay_revision_notes": "",
            "shots": [],
            "prompts": [],
            "prompts_approved": False,
            "prompt_revision_notes": "",
            "videos": [],
            "character_references": {},
            "current_stage": "starting",
            "error": None,
            "llm_model": "deepseek-v4-pro",
            "video_model": "",
            "video_provider": "seedance",
            "assembled_video_path": None,
        }

        events = []
        try:
            async for event in graph_with_mocks.astream(initial_state, config=config, stream_mode="values"):
                events.append(event)
        except Exception as e:
            # LangGraph raises an exception containing the interrupt
            pass

        # Graph should have reached screenplay_written stage
        last = events[-1] if events else {}
        assert last.get("current_stage") in ("screenplay_written", "screenplay_review", None)
        assert mock_cj.called  # story_analyzer ran
        assert mock_c.called   # screenplay_writer ran


@pytest.mark.asyncio
async def test_graph_resumes_after_screenplay_approval(graph_with_mocks):
    """Verify graph resumes and reaches prompts_review after approving screenplay."""
    from langgraph.types import Command

    with patch("drama_agent.services.llm_service.llm_service.complete_json", new_callable=AsyncMock) as mock_cj, \
         patch("drama_agent.services.llm_service.llm_service.complete", new_callable=AsyncMock) as mock_c, \
         patch("drama_agent.services.rag_service.rag_service.save_character_profile"), \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value=None):

        # story_analyzer returns analysis; storyboard returns shots; prompt_engineer returns prompt
        mock_cj.side_effect = [STORY_ANALYSIS, SHOTS_DATA, PROMPT_DATA]
        mock_c.return_value = "INT. CITY - DAY\nHero stands tall.\n"

        config = {"configurable": {"thread_id": "test-project-2"}}
        initial_state = {
            "project_id": "test-project-2",
            "title": "Test",
            "raw_input": "A hero story",
            "genre": "action",
            "story_analysis": None,
            "screenplay": "",
            "screenplay_approved": False,
            "screenplay_revision_notes": "",
            "shots": [],
            "prompts": [],
            "prompts_approved": False,
            "prompt_revision_notes": "",
            "videos": [],
            "character_references": {},
            "current_stage": "starting",
            "error": None,
            "llm_model": "deepseek-v4-pro",
            "video_model": "",
            "video_provider": "seedance",
            "assembled_video_path": None,
        }

        # Run until first interrupt (screenplay_review)
        try:
            async for _ in graph_with_mocks.astream(initial_state, config=config, stream_mode="values"):
                pass
        except Exception:
            pass

        # Resume with approval
        events = []
        try:
            async for event in graph_with_mocks.astream(
                Command(resume={"approved": True, "notes": ""}),
                config=config,
                stream_mode="values",
            ):
                events.append(event)
        except Exception:
            pass

        stages = [e.get("current_stage") for e in events]
        # After approval, should proceed through storyboard → prompt_engineer → prompts_review
        assert any(s in ("storyboard_ready", "prompts_ready", "prompts_review") for s in stages), \
            f"Expected progression past screenplay approval, got stages: {stages}"
