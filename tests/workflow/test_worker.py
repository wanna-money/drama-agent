import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
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
async def test_worker_processes_one_job(factory):
    from drama_agent.workflow.worker import JobWorker
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind, JobStatus
    from drama_agent.db.models import Job
    async with factory() as s:
        await js.enqueue(s, JobKind.START, "p1", dedup_key="start")

    with patch("drama_agent.workflow.worker.runner.run_job", new=AsyncMock()) as mock_run:
        w = JobWorker(instance_id="A", poll_interval=0.01, heartbeat_timeout=60)
        task = asyncio.create_task(w.run_forever())
        await asyncio.sleep(0.15)
        await w.stop()
        await task
    mock_run.assert_awaited()
    async with factory() as s:
        row = (await s.execute(select(Job))).scalar_one()
        assert row.status == JobStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_worker_marks_failed_after_max_attempts(factory):
    from drama_agent.workflow.worker import JobWorker
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind, JobStatus
    from drama_agent.db.models import Job
    async with factory() as s:
        j = await js.enqueue(s, JobKind.START, "p1", dedup_key="start")
        row = await s.get(Job, j["id"])
        row.max_attempts = 1
        await s.commit()

    with patch("drama_agent.workflow.worker.runner.run_job",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        w = JobWorker(instance_id="A", poll_interval=0.01, heartbeat_timeout=60)
        task = asyncio.create_task(w.run_forever())
        await asyncio.sleep(0.15)
        await w.stop()
        await task
    async with factory() as s:
        row = (await s.execute(select(Job))).scalar_one()
        assert row.status == JobStatus.FAILED.value
