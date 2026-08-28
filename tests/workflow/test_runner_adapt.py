import pytest
from unittest.mock import AsyncMock
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


async def _setup(monkeypatch):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base, Project
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)
    async with factory() as s:
        s.add(Project(id="p", title="小说作品", genre="drama", source_text="正文"))
        await s.commit()
    return engine, factory


@pytest.mark.asyncio
async def test_adapt_job_runs_adaptation_and_never_touches_the_graph(monkeypatch):
    """kind=adapt 必须走改编路径 —— 走错会去跑集级图(thread_id 还是 project_id),后果不可控。"""
    from drama_agent.workflow import runner
    from drama_agent.services import adaptation_service
    engine, _factory = await _setup(monkeypatch)
    seen = {}

    async def fake_adapt(session, project_id):
        seen["pid"] = project_id
        return {"adaptation_status": "draft_ready", "adapted_draft": [{"index": 1}]}

    monkeypatch.setattr(adaptation_service, "adapt", fake_adapt)
    graph_mock = AsyncMock()
    monkeypatch.setattr(runner, "get_graph", graph_mock)

    await runner.run_job({"kind": "adapt", "episode_id": "p", "project_id": "p"})

    assert seen["pid"] == "p"
    graph_mock.assert_not_called()
    await engine.dispose()


@pytest.mark.asyncio
async def test_adapt_job_marks_project_failed_then_reraises(monkeypatch):
    """LLM 传输层异常:先把作品标 failed(否则 UI 永远停在 adapting),再抛给 job 重试。"""
    from drama_agent.db.models import Project
    from drama_agent.workflow import runner
    from drama_agent.services import adaptation_service
    engine, factory = await _setup(monkeypatch)

    async def boom(session, project_id):
        raise RuntimeError("LLM 超时")

    monkeypatch.setattr(adaptation_service, "adapt", boom)
    monkeypatch.setattr(runner, "get_graph", AsyncMock())

    with pytest.raises(RuntimeError):
        await runner.run_job({"kind": "adapt", "episode_id": "p", "project_id": "p"})

    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "failed"
    await engine.dispose()
