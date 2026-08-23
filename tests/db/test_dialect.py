import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_next_event_seq_increments(session):
    from drama_agent.db import dialect
    from drama_agent.db.models import Event
    s1 = await dialect.next_event_seq(session, "e1")
    session.add(Event(episode_id="e1", project_id="p1", seq=s1, type="stage_change", payload_json={}))
    await session.commit()
    s2 = await dialect.next_event_seq(session, "e1")
    assert s1 == 1 and s2 == 2


@pytest.mark.asyncio
async def test_event_seq_scoped_per_episode(session):
    """seq 按 episode 自增:两集各自从 1 开始,互不干扰(uq_event_seq 改约束后的核心回归)。"""
    from drama_agent.db import dialect
    from drama_agent.db.models import Event
    a1 = await dialect.next_event_seq(session, "epA")
    session.add(Event(episode_id="epA", project_id="p1", seq=a1, type="x", payload_json={}))
    await session.commit()
    b1 = await dialect.next_event_seq(session, "epB")  # 另一集,仍应从 1 起
    assert a1 == 1 and b1 == 1


@pytest.mark.asyncio
async def test_claim_one_job_atomic(session):
    from drama_agent.db import dialect
    from drama_agent.db.models import Job
    session.add(Job(id="j1", episode_id="e1", project_id="p1", kind="start", status="queued", dedup_key="start"))
    await session.commit()
    claimed = await dialect.claim_one_job(session, owner="inst-A")
    assert claimed is not None and claimed["id"] == "j1"
    assert claimed["status"] == "running" and claimed["owner"] == "inst-A"
    assert await dialect.claim_one_job(session, owner="inst-B") is None
