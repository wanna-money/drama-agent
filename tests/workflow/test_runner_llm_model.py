import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db import session as db_session
from drama_agent.db.enums import LifecycleStatus
from drama_agent.db.models import Base, Episode


@pytest.fixture
async def mem_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Local)
    yield Local
    await engine.dispose()


async def _mk_episode(Local, llm_model):
    eid = str(uuid.uuid4())
    async with Local() as s:
        s.add(Episode(id=eid, project_id="p1", episode_number=1, title="T", script_id="",
                      status=LifecycleStatus.CREATED.value, llm_model=llm_model))
        await s.commit()
    return eid


@pytest.mark.asyncio
async def test_initial_state_uses_stored_llm_model(mem_session):
    from drama_agent.workflow.runner import _build_initial_state
    eid = await _mk_episode(mem_session, "kimi-k2")
    state = await _build_initial_state(eid)
    assert state["llm_model"] == "kimi-k2"


@pytest.mark.asyncio
async def test_initial_state_falls_back_when_empty(mem_session, monkeypatch):
    """空模型名会让每个 LLM 节点在运行时才炸;兜底到该 kind 的有效默认。"""
    import drama_agent.provider as pp
    from drama_agent.provider.base import Model
    from drama_agent.workflow.runner import _build_initial_state
    eid = await _mk_episode(mem_session, "")
    fake = type("R", (), {
        "effective_default": lambda self, k: Model(
            id="fallback-llm", label="F", provider="p", kind="llm"),
    })()
    monkeypatch.setattr(pp, "provider_registry", fake)
    state = await _build_initial_state(eid)
    assert state["llm_model"] == "fallback-llm"


@pytest.mark.asyncio
async def test_build_initial_state_three_source_flows():
    """三条来源各自的 screenplay/approved:
    从故事(空)→ approved False;复用剧本 → approved True + 剧本正文;改编切片 → approved True + 切片。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base, Project, Episode, Script
    from drama_agent.workflow import runner
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = factory
    try:
        async with factory() as s:
            s.add(Project(id="p", title="t", genre="drama"))
            s.add(Script(id="sc", project_id="p", title="t", content="复用剧本正文"))
            s.add(Episode(id="e_story", project_id="p", episode_number=1, title="故事集",
                          status="created"))
            s.add(Episode(id="e_reuse", project_id="p", episode_number=2, title="复用集",
                          script_id="sc", status="created"))
            s.add(Episode(id="e_adapt", project_id="p", episode_number=3, title="改编集",
                          status="created",
                          screenplay_versions=[{"screenplay": "切片正文", "label": "分集剧本"}],
                          screenplay_version_current=0))
            await s.commit()
        st_story = await runner._build_initial_state("e_story")
        st_reuse = await runner._build_initial_state("e_reuse")
        st_adapt = await runner._build_initial_state("e_adapt")
    finally:
        db_session.AsyncSessionLocal = orig
        await engine.dispose()
    assert st_story["screenplay_approved"] is False and st_story["screenplay"] == ""
    assert st_reuse["screenplay_approved"] is True and st_reuse["screenplay"] == "复用剧本正文"
    assert st_adapt["screenplay_approved"] is True and st_adapt["screenplay"] == "切片正文"
