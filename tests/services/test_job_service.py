import pytest
from datetime import datetime, timezone, timedelta
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
async def test_enqueue_idempotent(session):
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind
    j1 = await js.enqueue(session, JobKind.START, "p1", dedup_key="start")
    j2 = await js.enqueue(session, JobKind.START, "p1", dedup_key="start")
    assert j1["id"] == j2["id"]  # 命中既有，不新建


@pytest.mark.asyncio
async def test_claim_next_then_empty(session):
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind
    await js.enqueue(session, JobKind.START, "p1", dedup_key="start")
    got = await js.claim_next(session, owner="A")
    assert got["status"] == "running"
    assert await js.claim_next(session, owner="A") is None


@pytest.mark.asyncio
async def test_requeue_and_mark(session):
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind
    j = await js.enqueue(session, JobKind.START, "p1", dedup_key="start")
    await js.claim_next(session, owner="A")
    await js.requeue(session, j["id"])
    got = await js.claim_next(session, owner="B")
    assert got["attempts"] == 1 and got["owner"] == "B"
    await js.mark_failed(session, j["id"], "boom")


@pytest.mark.asyncio
async def test_reap_stale_requeues_timed_out(session):
    from drama_agent.services import job_service as js
    from drama_agent.db.models import Job
    from drama_agent.db.enums import JobKind
    j = await js.enqueue(session, JobKind.START, "p1", dedup_key="start")
    await js.claim_next(session, owner="A")
    row = await session.get(Job, j["id"])
    row.heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=999)
    await session.commit()
    reaped = await js.reap_stale(session, timeout_seconds=60)
    assert reaped == 1
    assert (await js.claim_next(session, owner="B"))["attempts"] == 1


@pytest.mark.asyncio
async def test_enqueue_dedups_while_running_but_rearms_after_terminal(session):
    """#1: 非终态同键去重;终态(succeeded)则重新武装该行 → 打回后的新决策能入队。"""
    from drama_agent.services import job_service as js
    from drama_agent.db.enums import JobKind
    j1 = await js.enqueue(session, JobKind.RESUME, "p1", dedup_key="resume:x",
                          payload={"approved": False})
    await js.claim_next(session, owner="A")  # running
    # 运行中重复入队 → 去重(同一 job,不新建、不改 payload)
    j2 = await js.enqueue(session, JobKind.RESUME, "p1", dedup_key="resume:x",
                          payload={"approved": True})
    assert j2["id"] == j1["id"] and j2["status"] == "running"
    assert j2["payload_json"] == {"approved": False}  # 非终态不被覆盖
    # 该 resume 完成后,用户带新决策再提交 → 重新武装:回到 queued + 新 payload
    await js.mark_succeeded(session, j1["id"])
    j3 = await js.enqueue(session, JobKind.RESUME, "p1", dedup_key="resume:x",
                          payload={"approved": True})
    assert j3["id"] == j1["id"] and j3["status"] == "queued"
    assert j3["payload_json"] == {"approved": True} and j3["attempts"] == 0
    # 可被重新领取执行(不再永久卡死)
    assert (await js.claim_next(session, owner="B"))["id"] == j1["id"]


@pytest.mark.asyncio
async def test_fail_or_requeue_uses_db_attempts_not_snapshot(session):
    """#7: 判定读 DB 真值。未超 max → requeued;达到 max → failed。"""
    from drama_agent.services import job_service as js
    from drama_agent.db.models import Job
    from drama_agent.db.enums import JobKind
    j = await js.enqueue(session, JobKind.START, "p1", dedup_key="start")  # attempts=0,max=3
    assert await js.fail_or_requeue(session, j["id"], "e") == "requeued"
    # 把 DB attempts 顶到 max-1(=2),再失败一次应判死(2+1==3 不 < 3)
    row = await session.get(Job, j["id"])
    row.attempts = 2
    await session.commit()
    assert await js.fail_or_requeue(session, j["id"], "boom") == "failed"
    row = await session.get(Job, j["id"])
    assert row.status == "failed" and row.error_message == "boom"
    assert await js.fail_or_requeue(session, "no-such-id", "e") == "gone"
