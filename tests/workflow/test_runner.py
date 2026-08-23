import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def db_setup():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base, Project, Episode, Script
    from drama_agent.db.enums import LifecycleStatus
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = factory
    async with factory() as s:
        s.add(Project(id="p1", title="t", genre="drama"))
        # 视频图从 completed Script 起跑(剧本已 approved),Episode 靠 script_id 关联
        s.add(Script(id="s1", project_id="p1", title="t", source_text="r",
                     content="剧本正文", story_analysis={"genre": "drama"},
                     status=LifecycleStatus.COMPLETED.value))
        s.add(Episode(id="e1", project_id="p1", episode_number=1, title="t", script_id="s1",
                      status=LifecycleStatus.QUEUED.value))
        await s.commit()
    yield factory
    db_session.AsyncSessionLocal = orig
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_job_writes_events_and_completes(db_setup):
    from drama_agent.workflow import runner
    from drama_agent.services import event_service as ev
    from drama_agent.db.models import Episode

    async def fake_astream(initial, config, stream_mode):
        for stage in ("story_analyzed", "completed"):
            yield {"current_stage": stage, "title": "t"}

    fake_graph = MagicMock()
    fake_graph.astream = fake_astream
    fake_state = MagicMock()
    fake_state.next = ()          # 无中断 → 完成
    fake_state.values = {"current_stage": "completed", "title": "t"}
    fake_graph.aget_state = AsyncMock(return_value=fake_state)

    with patch("drama_agent.workflow.runner.get_video_graph", new=AsyncMock(return_value=fake_graph)):
        await runner.run_job({"id": "j1", "episode_id": "e1", "project_id": "p1",
                              "kind": "start", "payload_json": None})

    async with db_setup() as s:
        evts = await ev.fetch_since(s, "e1", 0)
        ep = await s.get(Episode, "e1")
    types = [e["type"] for e in evts]
    assert "stage_change" in types and "completed" in types
    assert ep.status == "completed"


@pytest.mark.asyncio
async def test_run_job_pauses_on_interrupt(db_setup):
    from drama_agent.workflow import runner
    from drama_agent.db.models import Episode

    async def fake_astream(initial, config, stream_mode):
        yield {"current_stage": "screenplay_written", "title": "t"}

    fake_graph = MagicMock()
    fake_graph.astream = fake_astream
    fake_state = MagicMock()
    fake_state.next = ("screenplay_review",)   # 停在中断
    fake_state.values = {"current_stage": "screenplay_written"}
    fake_graph.aget_state = AsyncMock(return_value=fake_state)

    with patch("drama_agent.workflow.runner.get_video_graph", new=AsyncMock(return_value=fake_graph)):
        await runner.run_job({"id": "j2", "episode_id": "e1", "project_id": "p1",
                              "kind": "start", "payload_json": None})

    async with db_setup() as s:
        ep = await s.get(Episode, "e1")
    assert ep.status == "paused"
    # 中断点写进 snapshot.paused_at,供前端判断停在哪个审核步
    assert ep.state_snapshot.get("paused_at") == "screenplay_review"
