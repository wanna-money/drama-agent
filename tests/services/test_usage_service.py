import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select


@pytest.fixture
async def db():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    yield db_session
    db_session.AsyncSessionLocal = orig
    await eng.dispose()


@pytest.mark.asyncio
async def test_record_llm_writes_with_context(db):
    from drama_agent.services import usage_service
    from drama_agent.workflow.usage_context import set_usage_context
    from drama_agent.db.models import UsageRecord
    set_usage_context(entity_id="e1", project_id="p1", is_script=False, node="screenplay_writer")
    await usage_service.record_llm({"input": 100, "output": 50}, provider="deepseek", model="deepseek-v4-pro")
    async with db.AsyncSessionLocal() as s:
        rows = (await s.execute(select(UsageRecord))).scalars().all()
    assert len(rows) == 1
    r = rows[0]
    assert r.entity_id == "e1" and r.node == "screenplay_writer" and r.kind == "llm"
    assert r.input_tokens == 100 and r.output_tokens == 50 and r.model == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_record_noop_without_context(db):
    from drama_agent.services import usage_service
    from drama_agent.workflow.usage_context import _ctx
    from drama_agent.db.models import UsageRecord
    _ctx.set(None)
    await usage_service.record_llm({"input": 10, "output": 5}, provider="x", model="m")
    async with db.AsyncSessionLocal() as s:
        rows = (await s.execute(select(UsageRecord))).scalars().all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_record_swallows_write_error(db):
    from drama_agent.services import usage_service
    from drama_agent.workflow.usage_context import set_usage_context
    set_usage_context(entity_id="e1", project_id="p1", is_script=False, node="n")
    with patch.object(db, "AsyncSessionLocal", side_effect=RuntimeError("boom")):
        await usage_service.record_llm({"input": 1, "output": 1}, provider="x", model="m")  # 不抛即通过


@pytest.mark.asyncio
async def test_record_video_explicit_attribution(db):
    from drama_agent.services import usage_service
    from drama_agent.db.models import UsageRecord
    from drama_agent.workflow.usage_context import _ctx
    _ctx.set(None)
    await usage_service.record_video(provider="seedance", model="seedance-2.0", seconds=5,
                                     entity_id="ep1", project_id="p1", is_script=False, node="regenerate")
    async with db.AsyncSessionLocal() as s:
        rows = (await s.execute(select(UsageRecord))).scalars().all()
    assert len(rows) == 1 and rows[0].video_seconds == 5 and rows[0].entity_id == "ep1" and rows[0].kind == "video"
