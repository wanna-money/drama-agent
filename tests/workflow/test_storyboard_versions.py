"""分镜版本树:storyboard_director_node 每次(重新)生成追加一版(不覆盖),
episode_service 的读写侧对齐 screenplay_versions 同构实现。
"""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from drama_agent.db.models import Base, Episode
from drama_agent.services import episode_service
from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


async def _make_episode(session, **overrides) -> Episode:
    row = Episode(
        id="ep-1", project_id="proj-1", episode_number=1, title="t1",
        story_id="story-1", status="running",
        **overrides,
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_append_shots_version_db_seeds_first_version(db_session):
    await _make_episode(db_session)
    shots = [{"shot_id": "s1", "duration_seconds": 3}]

    result = await episode_service.append_shots_version_db(
        db_session, "ep-1", shots=shots, label="初始生成")

    assert result == {"version_index": 0, "versions_len": 1}
    row = (await db_session.execute(
        select(Episode).where(Episode.id == "ep-1"))).scalar_one()
    assert row.shots_versions == [
        {"shots": shots, "label": "初始生成", "created_at": row.shots_versions[0]["created_at"]}
    ]
    assert row.shots_version_current == 0


@pytest.mark.asyncio
async def test_append_shots_version_db_appends_without_overwriting(db_session):
    """退回重新生成必须追加第二版,第一版仍留在版本树里可回看。"""
    await _make_episode(db_session)
    v0 = [{"shot_id": "s1", "duration_seconds": 3}]
    v1 = [{"shot_id": "s2", "duration_seconds": 7}]
    await episode_service.append_shots_version_db(db_session, "ep-1", shots=v0, label="初始生成")

    result = await episode_service.append_shots_version_db(
        db_session, "ep-1", shots=v1, label="镜头太少，请增加冲突镜头")

    assert result == {"version_index": 1, "versions_len": 2}
    row = (await db_session.execute(
        select(Episode).where(Episode.id == "ep-1"))).scalar_one()
    assert len(row.shots_versions) == 2
    assert row.shots_versions[0]["shots"] == v0
    assert row.shots_versions[1]["shots"] == v1
    assert row.shots_version_current == 1


@pytest.mark.asyncio
async def test_append_shots_version_db_truncates_long_label(db_session):
    await _make_episode(db_session)
    long_label = "x" * 200

    await episode_service.append_shots_version_db(
        db_session, "ep-1", shots=[], label=long_label)

    row = (await db_session.execute(
        select(Episode).where(Episode.id == "ep-1"))).scalar_one()
    assert len(row.shots_versions[0]["label"]) == 80


@pytest.mark.asyncio
async def test_set_current_shots_version_switches_and_writes_snapshot(db_session):
    await _make_episode(db_session)
    v0 = [{"shot_id": "s1", "duration_seconds": 3}]
    v1 = [{"shot_id": "s2", "duration_seconds": 7}]
    await episode_service.append_shots_version_db(db_session, "ep-1", shots=v0, label="初始生成")
    await episode_service.append_shots_version_db(db_session, "ep-1", shots=v1, label="重新生成")

    result = await episode_service.set_current_shots_version(db_session, "ep-1", 0)

    assert result == {"shots": v0, "version_index": 0}
    row = (await db_session.execute(
        select(Episode).where(Episode.id == "ep-1"))).scalar_one()
    assert row.shots_version_current == 0
    assert row.state_snapshot["shots"] == v0


@pytest.mark.asyncio
async def test_set_current_shots_version_out_of_range_raises(db_session):
    await _make_episode(db_session)
    await episode_service.append_shots_version_db(
        db_session, "ep-1", shots=[{"shot_id": "s1"}], label="初始生成")

    with pytest.raises(IndexError):
        await episode_service.set_current_shots_version(db_session, "ep-1", 5)


@pytest.mark.asyncio
async def test_storyboard_director_node_appends_version_with_notes_as_label(monkeypatch):
    """退回重新生成时(有 storyboard_revision_notes)追加的版本 label 取自这份意见。"""
    from drama_agent.services import cast_service

    monkeypatch.setattr(cast_service, "roster_names", AsyncMock(return_value=[]))
    monkeypatch.setattr(cast_service, "roster_by_id", AsyncMock(return_value={}))
    monkeypatch.setattr(cast_service, "canonical_cast", lambda cast, roster: cast or {})

    shot = {
        "scene_number": 1, "shot_number": 1, "shot_type": "MS",
        "camera_movement": "static", "lighting": "natural", "color_temp": "neutral",
        "duration_seconds": 3, "beats": None, "location": "INT", "description": "d",
        "characters": [], "action": "he moves", "dialogue": "",
    }
    from drama_agent.services.llm_service import llm_service
    monkeypatch.setattr(llm_service, "complete_json", AsyncMock(return_value=[shot, {**shot, "duration_seconds": 6}, {**shot, "duration_seconds": 1}]))

    state = {
        "project_id": "proj-1", "episode_id": "ep-1", "target_seconds": 60,
        "screenplay": "INT. ROOM\nAction.", "story_analysis": {}, "llm_model": None,
        "cast": {}, "storyboard_revision_notes": "镜头太少，请增加冲突镜头",
    }

    append_mock = AsyncMock(return_value={"version_index": 1, "versions_len": 2})
    with patch(
        "drama_agent.services.episode_service.append_shots_version_db", append_mock
    ):
        result = await storyboard_director_node(state)

    assert result["current_stage"] == "storyboard_ready"
    append_mock.assert_awaited_once()
    _, kwargs = append_mock.call_args
    assert kwargs["label"] == "镜头太少，请增加冲突镜头"
