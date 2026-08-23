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
async def test_story_analyzer_returns_analysis(monkeypatch):
    """story_analyzer_node calls LLM and returns structured analysis + persists characters."""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
    from drama_agent.services import character_service
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=STORY_ANALYSIS):
        result = await story_analyzer_node(make_base_state())

    assert result["current_stage"] == "story_analyzed"
    assert result["story_analysis"]["title"] == "Hero's Journey"
    assert result["story_analysis"]["characters"][0]["name"] == "Hero"
    async with factory() as s:
        assert await character_service.get(s, "proj-test", "Hero") == \
            STORY_ANALYSIS["characters"][0]["appearance"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_story_analyzer_updates_title(monkeypatch):
    """story_analyzer_node updates title from analysis."""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal",
                        async_sessionmaker(engine, expire_on_commit=False))

    analysis = {**STORY_ANALYSIS, "title": "Extracted Title"}
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=analysis):
        result = await story_analyzer_node(make_base_state(title="Original Title"))

    assert result["title"] == "Extracted Title"
    await engine.dispose()


@pytest.mark.asyncio
async def test_story_analyzer_multiple_characters(monkeypatch):
    """story_analyzer_node persists all characters."""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
    from drama_agent.services import character_service
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)

    analysis = {**STORY_ANALYSIS, "characters": [
        {"name": "Hero", "appearance": "tall man", "personality": "brave", "reference_image_url": None},
        {"name": "Villain", "appearance": "dark coat", "personality": "cunning", "reference_image_url": None},
    ]}
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=analysis):
        await story_analyzer_node(make_base_state())

    async with factory() as s:
        assert await character_service.get(s, "proj-test", "Hero") == "tall man"
        assert await character_service.get(s, "proj-test", "Villain") == "dark coat"
    await engine.dispose()


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
async def test_storyboard_invalid_shot_type_falls_back_to_default():
    """模型给了枚举外的 shot_type/camera_movement → fallback 到默认合法值。"""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node
    from drama_agent.workflow.constants import ShotType, CameraMovement

    bad = [{**SHOTS_RAW[0], "shot_type": "wide-ish", "camera_movement": "swirl"}]
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=bad):
        result = await storyboard_director_node(make_base_state(
            screenplay="screenplay", story_analysis=STORY_ANALYSIS,
        ))

    shot = result["shots"][0]
    assert shot["shot_type"] == ShotType.MS.value
    assert shot["camera_movement"] == CameraMovement.STATIC.value


@pytest.mark.asyncio
async def test_storyboard_valid_shot_type_preserved():
    """合法值原样保留(不被 fallback 误伤)。"""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node
    from drama_agent.workflow.constants import ShotType

    good = [{**SHOTS_RAW[0], "shot_type": "ECU", "camera_movement": "dolly"}]
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=good):
        result = await storyboard_director_node(make_base_state(
            screenplay="screenplay", story_analysis=STORY_ANALYSIS,
        ))

    assert result["shots"][0]["shot_type"] == ShotType.ECU.value
    assert result["shots"][0]["camera_movement"] == "dolly"


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


@pytest.fixture
async def pe_db(monkeypatch):
    """In-memory DB for prompt_engineer (which reads character_service)."""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_engineer_creates_prompts(pe_db):
    """prompt_engineer_node creates one PromptDict per shot."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    prompt_result = {"prompt_text": "Epic city shot, cinematic", "negative_prompt": "blurry"}
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value=prompt_result):
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
async def test_prompt_engineer_passes_revision_notes_to_llm(pe_db):
    """state 里带 prompt_revision_notes 时(退回重新生成路径),必须真正传给 LLM 而不是被无视。"""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    captured_user_prompts = []

    async def fake_complete_json(system, user, **kwargs):
        captured_user_prompts.append(user)
        return {"prompt_text": "revised shot", "negative_prompt": "bad"}

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, side_effect=fake_complete_json):
        await prompt_engineer_node(make_base_state(
            shots=make_shots(), story_analysis=STORY_ANALYSIS,
            prompt_revision_notes="镜头太暗，改成白天室外场景",
        ))

    assert len(captured_user_prompts) == 2
    for user_prompt in captured_user_prompts:
        assert "镜头太暗，改成白天室外场景" in user_prompt


@pytest.mark.asyncio
async def test_prompt_engineer_first_shot_no_frame_chain(pe_db):
    """First shot has no reference_role for frame chaining."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}):
        result = await prompt_engineer_node(make_base_state(shots=make_shots()))

    first_prompt = result["prompts"][0]
    assert first_prompt["reference_role"] is None
    assert first_prompt["reference_image_url"] is None


@pytest.mark.asyncio
async def test_prompt_engineer_second_shot_has_frame_chain(pe_db):
    """Subsequent shots get reference_role='first_frame' for continuity."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}):
        result = await prompt_engineer_node(make_base_state(shots=make_shots()))

    second_prompt = result["prompts"][1]
    assert second_prompt["reference_role"] == "first_frame"


@pytest.mark.asyncio
async def test_prompt_engineer_uses_character_reference(pe_db):
    """prompt_engineer uses character_references for subject_reference."""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node

    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               new_callable=AsyncMock, return_value={"prompt_text": "shot", "negative_prompt": "bad"}):
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
async def test_story_analyzer_tolerates_missing_character_keys(monkeypatch):
    """story_analyzer_node should not crash when LLM returns characters without name/appearance."""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.workflow.nodes.story_analyzer import story_analyzer_node
    from drama_agent.services import character_service
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)

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
        result = await story_analyzer_node(make_base_state())

    # Only the complete character should be persisted
    async with factory() as s:
        assert await character_service.get(s, "proj-test", "Villain") == "dark cloak"
        assert await character_service.get(s, "proj-test", "Hero") is None
    assert result["current_stage"] == "story_analyzed"
    await engine.dispose()


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


def test_storyboard_formats_characters_skips_incomplete():
    """_format_characters should skip chars missing name or appearance."""
    from drama_agent.workflow.nodes.storyboard_director import _format_characters

    analysis = {
        "characters": [
            {"name": "Alice", "appearance": "blonde hair"},
            {"name": "Bob"},   # missing appearance
            {"appearance": "tall"},  # missing name
        ]
    }
    result = _format_characters(analysis)
    assert "Alice" in result
    assert "Bob" not in result


@pytest.mark.asyncio
async def test_prompts_review_node_merges_edited_negative_prompts():
    """approved=True 时,decision 里的 edited_negative_prompts 必须按 shot_id 合并进返回的 prompts。"""
    from drama_agent.workflow.graph import prompts_review_node

    state = {
        "prompts": [
            {"shot_id": "s1", "prompt_text": "a", "negative_prompt": "orig-neg-1",
             "reference_image_url": None, "reference_role": None, "approved": False,
             "edited_prompt": None, "edited_negative_prompt": None, "keyframe_url": None},
            {"shot_id": "s2", "prompt_text": "b", "negative_prompt": "orig-neg-2",
             "reference_image_url": None, "reference_role": None, "approved": False,
             "edited_prompt": None, "edited_negative_prompt": None, "keyframe_url": None},
        ],
        "shots": [],
    }
    decision = {
        "approved": True,
        "edited_prompts": {},
        "edited_negative_prompts": {"s1": "new-neg-1"},
        "notes": "",
    }
    with patch("drama_agent.workflow.graph.interrupt", return_value=decision):
        result = await prompts_review_node(state)

    by_id = {p["shot_id"]: p for p in result["prompts"]}
    assert by_id["s1"]["edited_negative_prompt"] == "new-neg-1"
    assert by_id["s2"]["edited_negative_prompt"] is None
    assert result["prompts_approved"] is True


@pytest.mark.asyncio
async def test_prompts_review_node_merges_positive_and_negative_edits_independently():
    """正向/负向编辑互不影响:同一镜头可只改一边、也可两边都改。"""
    from drama_agent.workflow.graph import prompts_review_node

    def _p(shot_id):
        return {"shot_id": shot_id, "prompt_text": f"txt-{shot_id}",
                "negative_prompt": f"neg-{shot_id}", "reference_image_url": None,
                "reference_role": None, "approved": False, "edited_prompt": None,
                "edited_negative_prompt": None, "keyframe_url": None}

    state = {"prompts": [_p("both"), _p("pos"), _p("neg"), _p("none")], "shots": []}
    decision = {
        "approved": True,
        "edited_prompts": {"both": "P-both", "pos": "P-pos"},
        "edited_negative_prompts": {"both": "N-both", "neg": "N-neg"},
        "notes": "",
    }
    with patch("drama_agent.workflow.graph.interrupt", return_value=decision):
        result = await prompts_review_node(state)

    by_id = {p["shot_id"]: p for p in result["prompts"]}
    # 两边都改:互不覆盖
    assert by_id["both"]["edited_prompt"] == "P-both"
    assert by_id["both"]["edited_negative_prompt"] == "N-both"
    # 只改正向:负向保持 None
    assert by_id["pos"]["edited_prompt"] == "P-pos"
    assert by_id["pos"]["edited_negative_prompt"] is None
    # 只改负向:正向保持 None
    assert by_id["neg"]["edited_prompt"] is None
    assert by_id["neg"]["edited_negative_prompt"] == "N-neg"
    # 都没改
    assert by_id["none"]["edited_prompt"] is None
    assert by_id["none"]["edited_negative_prompt"] is None
    # 原始字段不被破坏,且全部置为 approved
    assert by_id["both"]["prompt_text"] == "txt-both"
    assert by_id["both"]["negative_prompt"] == "neg-both"
    assert all(p["approved"] is True for p in result["prompts"])
