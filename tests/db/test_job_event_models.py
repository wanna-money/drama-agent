import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.exc import IntegrityError


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
async def test_job_unique_dedup(session):
    """dedup 唯一约束按 episode 作用域:同 episode 同 (kind,dedup_key) 冲突。"""
    from drama_agent.db.models import Job
    session.add(Job(id="j1", episode_id="e1", project_id="p1", kind="start", status="queued", dedup_key="start"))
    await session.commit()
    session.add(Job(id="j2", episode_id="e1", project_id="p1", kind="start", status="queued", dedup_key="start"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_job_dedup_scoped_per_episode(session):
    """同项目不同集用相同 (kind,dedup_key) 不冲突(作用域是 episode 而非 project)。"""
    from drama_agent.db.models import Job
    session.add(Job(id="j1", episode_id="epA", project_id="p1", kind="start", status="queued", dedup_key="start"))
    session.add(Job(id="j2", episode_id="epB", project_id="p1", kind="start", status="queued", dedup_key="start"))
    await session.commit()  # 不应抛异常
    from sqlalchemy import select, func
    n = (await session.execute(select(func.count()).select_from(Job))).scalar()
    assert n == 2

