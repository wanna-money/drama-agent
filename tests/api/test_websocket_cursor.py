import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def factory():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = f
    yield f
    db_session.AsyncSessionLocal = orig
    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_returns_events_after_seq(factory):
    from drama_agent.api.websocket import backfill_events
    from drama_agent.services import event_service as ev
    from drama_agent.db.enums import EventType
    async with factory() as s:
        await ev.append_event(s, "p1", EventType.STAGE_CHANGE, {"n": 1})
        await ev.append_event(s, "p1", EventType.STAGE_CHANGE, {"n": 2})

    got = await backfill_events("p1", after_seq=1)
    assert [e["seq"] for e in got] == [2]
