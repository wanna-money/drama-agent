"""Tests for workflow nodes — story_analyzer, screenplay_writer, storyboard_director, prompt_engineer."""
import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock


def make_base_state(**overrides):
    state = {
        "project_id": "proj-test",
        "title": "Test Drama",
        "raw_input": "A hero saves the world.",
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
    state.update(overrides)
    return state


STORY_ANALYSIS = {
    "title": "Hero's Journey",
    "genre": "action",
    "setting": "Modern city, present day",
    "themes": ["courage", "sacrifice"],
    "tone": "serious",
    "scene_count_estimate": 3,
    "plot_summary": "A hero rises to save the city.",
    "characters": [
        {
            "name": "Hero",
            "appearance": "Tall man, short black hair, red cape, muscular build",
            "personality": "Brave and determined",
            "reference_image_url": None,
        }
    ],
}


# ── story_analyzer ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_story_analyzer_returns_analysis():
    """story_analyzer_node calls LLM and returns structured analysis."""
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=STORY_ANALYSIS), \
         patch("drama_agent.services.rag_service.rag_service.save_character_profile") as mock_save:

        result = await story_analyzer_node(make_base_state())

    assert result["current_stage"] == "story_analyzed"
    assert result["story_analysis"]["title"] == "Hero's Journey"
    assert result["story_analysis"]["characters"][0]["name"] == "Hero"
    mock_save.assert_called_once_with("proj-test", "Hero", STORY_ANALYSIS["characters"][0]["appearance"])


@pytest.mark.asyncio
async def test_story_analyzer_updates_title():
    """story_analyzer_node updates title from analysis."""
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node

    analysis = {**STORY_ANALYSIS, "title": "Extracted Title"}
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=analysis), \
         patch("drama_agent.services.rag_service.rag_service.save_character_profile"):

        result = await story_analyzer_node(make_base_state(title="Original Title"))

    assert result["title"] == "Extracted Title"


@pytest.mark.asyncio
async def test_story_analyzer_multiple_characters():
    """story_analyzer_node saves all characters to RAG."""
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node

    analysis = {**STORY_ANALYSIS, "characters": [
        {"name": "Hero", "appearance": "tall man", "personality": "brave", "reference_image_url": None},
        {"name": "Villain", "appearance": "dark coat", "personality": "cunning", "reference_image_url": None},
    ]}
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=analysis), \
         patch("drama_agent.services.rag_service.rag_service.save_character_profile") as mock_save:

        await story_analyzer_node(make_base_state())

    assert mock_save.call_count == 2


# ── screenplay_writer ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_screenplay_writer_produces_text():
    """screenplay_writer_node returns non-empty screenplay."""
    from drama_agent.workflow.nodes.screenplay_writer import screenplay_writer_node

    screenplay_text = "INT. CITY STREET - DAY\n\nHero walks through the crowd.\n\nHERO\nI must save them.\n"

    with patch("drama_agent.services.llm_service.llm_service.complete",
               new_callable=AsyncMock, return_value=screenplay_text):

        result = await screenplay_writer_node(make_base_state(story_analysis=STORY_ANALYSIS))

    assert result["screenplay"] == screenplay_text
    assert result["screenplay_approved"] is False
    assert result["current_stage"] == "screenplay_written"


@pytest.mark.asyncio
async def test_screenplay_writer_uses_characters():
    """screenplay_writer_node includes character info in LLM prompt."""
    from drama_agent.workflow.nodes.screenplay_writer import screenplay_writer_node

    captured_prompt = {}

    async def capture_complete(system, user, **kwargs):
        captured_prompt["user"] = user
        return "screenplay"

    with patch("drama_agent.services.llm_service.llm_service.complete", side_effect=capture_complete):
        await screenplay_writer_node(make_base_state(story_analysis=STORY_ANALYSIS))

    assert "Hero" in captured_prompt["user"]
    assert "Tall man" in captured_prompt["user"]


# ── storyboard_director ───────────────────────────────────────────────────────

SHOTS_RAW = [
    {
        "scene_number": 1, "shot_number": 1, "shot_type": "ELS",
        "camera_movement": "static", "duration_seconds": 5,
        "description": "City establishing shot", "characters": [],
        "action": "Busy city morning", "dialogue": "", "location": "EXT. CITY - DAY",
    },
    {
        "scene_number": 1, "shot_number": 2, "shot_type": "MS",
        "camera_movement": "pan", "duration_seconds": 8,
        "description": "Hero walks forward", "characters": ["Hero"],
        "action": "Hero strides confidently", "dialogue": "", "location": "EXT. CITY - DAY",
    },
]


@pytest.mark.asyncio
async def test_storyboard_creates_shots():
    """storyboard_director_node creates ShotDict entries with shot_ids."""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=SHOTS_RAW):

        result = await storyboard_director_node(make_base_state(
            screenplay="INT. CITY - DAY\n\nHero walks.",
            story_analysis=STORY_ANALYSIS,
        ))

    assert result["current_stage"] == "storyboard_ready"
    assert len(result["shots"]) == 2
    for shot in result["shots"]:
        assert "shot_id" in shot
        assert len(shot["shot_id"]) == 36  # UUID
        assert shot["duration_seconds"] <= 10  # capped


@pytest.mark.asyncio
async def test_storyboard_caps_duration():
    """storyboard_director_node caps duration_seconds to 10."""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node

    shots_with_long_duration = [{**SHOTS_RAW[0], "duration_seconds": 30}]
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=shots_with_long_duration):

        result = await storyboard_director_node(make_base_state(
            screenplay="screenplay", story_analysis=STORY_ANALYSIS,
        ))

    assert result["shots"][0]["duration_seconds"] == 10


@pytest.mark.asyncio
async def test_storyboard_handles_dict_response():
    """storyboard_director_node handles LLM returning {'shots': [...]} dict."""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"shots": SHOTS_RAW}):

        result = await storyboard_director_node(make_base_state(
            screenplay="screenplay", story_analysis=STORY_ANALYSIS,
        ))

    assert len(result["shots"]) == 2


# ── prompt_engineer ───────────────────────────────────────────────────────────

def make_shots():
    return [
        {
            "shot_id": "shot-001", "scene_number": 1, "shot_number": 1,
            "shot_type": "ELS", "camera_movement": "static", "duration_seconds": 5,
            "description": "City establishing", "characters": [],
            "action": "Morning city", "dialogue": "", "location": "EXT. CITY - DAY",
        },
        {
            "shot_id": "shot-002", "scene_number": 1, "shot_number": 2,
            "shot_type": "MS", "camera_movement": "pan", "duration_seconds": 5,
            "description": "Hero walks", "characters": ["Hero"],
            "action": "Hero strides", "dialogue": "", "location": "EXT. CITY - DAY",
        },
    ]


@pytest.mark.asyncio
async def test_prompt_engineer_creates_prompts():
    """prompt_engineer_node creates one PromptDict per shot."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    prompt_result = {"prompt_text": "Epic city shot, cinematic", "negative_prompt": "blurry"}

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=prompt_result), \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value=None):

        result = await prompt_engineer_node(make_base_state(
            shots=make_shots(), story_analysis=STORY_ANALYSIS,
        ))

    assert result["current_stage"] == "prompts_ready"
    assert len(result["prompts"]) == 2
    for p in result["prompts"]:
        assert p["prompt_text"] == "Epic city shot, cinematic"
        assert p["negative_prompt"] == "blurry"
        assert p["approved"] is False


@pytest.mark.asyncio
async def test_prompt_engineer_first_shot_no_frame_chain():
    """First shot has no reference_role for frame chaining."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}), \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value=None):

        result = await prompt_engineer_node(make_base_state(shots=make_shots()))

    first_prompt = result["prompts"][0]
    assert first_prompt["reference_role"] is None
    assert first_prompt["reference_image_url"] is None


@pytest.mark.asyncio
async def test_prompt_engineer_second_shot_has_frame_chain():
    """Subsequent shots get reference_role='first_frame' for continuity."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}), \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value=None):

        result = await prompt_engineer_node(make_base_state(shots=make_shots()))

    second_prompt = result["prompts"][1]
    assert second_prompt["reference_role"] == "first_frame"


@pytest.mark.asyncio
async def test_prompt_engineer_uses_character_reference():
    """prompt_engineer uses character_references for subject_reference."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}), \
         patch("drama_agent.services.rag_service.rag_service.query_prompt_templates", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.query_cinematography", return_value=[]), \
         patch("drama_agent.services.rag_service.rag_service.get_character_description", return_value="tall man"):

        result = await prompt_engineer_node(make_base_state(
            shots=make_shots(),
            character_references={"Hero": "http://hero-ref.jpg"},
        ))

    # Shot 2 has Hero character and we have a character_reference
    hero_prompt = result["prompts"][1]
    assert hero_prompt["reference_image_url"] == "http://hero-ref.jpg"
    assert hero_prompt["reference_role"] == "subject_reference"


@pytest.mark.asyncio
async def test_prompt_engineer_empty_shots():
    """prompt_engineer with no shots returns empty prompts list."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    result = await prompt_engineer_node(make_base_state(shots=[]))

    assert result["prompts"] == []
    assert result["current_stage"] == "prompts_ready"


# ── robustness: missing keys in LLM output ────────────────────────────────────

@pytest.mark.asyncio
async def test_story_analyzer_tolerates_missing_character_keys():
    """story_analyzer_node should not crash when LLM returns characters without name/appearance."""
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node

    incomplete_analysis = {
        "title": "Broken",
        "genre": "drama",
        "characters": [
            {"personality": "brave"},        # missing name and appearance
            {"name": "Hero"},                # missing appearance
            {"name": "Villain", "appearance": "dark cloak"},  # complete
        ],
    }
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=incomplete_analysis):
        with patch("drama_agent.services.rag_service.rag_service.save_character_profile") as mock_save:
            result = await story_analyzer_node(make_base_state())

    # Only the complete character should be saved
    assert mock_save.call_count == 1
    assert mock_save.call_args[0][1] == "Villain"
    assert result["current_stage"] == "story_analyzed"


@pytest.mark.asyncio
async def test_storyboard_tolerates_non_list_response():
    """storyboard_director_node should return empty shots list when LLM returns non-list."""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"error": "failed to parse"}):
        result = await storyboard_director_node(make_base_state(
            screenplay="screenplay", story_analysis=STORY_ANALYSIS,
        ))

    assert result["shots"] == []
    assert result["current_stage"] == "storyboard_ready"


@pytest.mark.asyncio
async def test_storyboard_formats_characters_skips_incomplete():
    """_format_characters should skip chars missing name or appearance."""
    from drama_agent.workflow.nodes.storyboard_director import _format_characters

    state = make_base_state(story_analysis={
        "characters": [
            {"name": "Alice", "appearance": "blonde hair"},
            {"name": "Bob"},   # missing appearance
            {"appearance": "tall"},  # missing name
        ]
    })
    result = _format_characters(state)
    assert "Alice" in result
    assert "Bob" not in result
