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
async def test_append_and_fetch_since(session):
    from drama_agent.services import event_service as ev
    from drama_agent.db.enums import EventType
    e1 = await ev.append_event(session, "p1", EventType.STAGE_CHANGE, {"stage": "a"})
    e2 = await ev.append_event(session, "p1", EventType.STAGE_CHANGE, {"stage": "b"})
    assert e1["seq"] == 1 and e2["seq"] == 2
    assert "created_at" in e1
    fresh = await ev.fetch_since(session, "p1", after_seq=1)
    assert [e["seq"] for e in fresh] == [2]
    assert fresh[0]["payload_json"] == {"stage": "b"}


@pytest.mark.asyncio
async def test_fetch_since_scoped_by_project(session):
    from drama_agent.services import event_service as ev
    from drama_agent.db.enums import EventType
    await ev.append_event(session, "p1", EventType.STAGE_CHANGE, {})
    await ev.append_event(session, "p2", EventType.STAGE_CHANGE, {})
    assert len(await ev.fetch_since(session, "p1", 0)) == 1


@pytest.mark.asyncio
async def test_append_event_recovers_from_seq_conflict(session, monkeypatch):
    """#6: 并发撞 uq_event_seq 时,savepoint 回滚事件插入 + 重算 seq 恢复,不抛 500。"""
    from drama_agent.services import event_service as ev
    from drama_agent.db import dialect
    from drama_agent.db.enums import EventType
    e1 = await ev.append_event(session, "p1", EventType.STAGE_CHANGE, {"n": 1})
    assert e1["seq"] == 1
    # 模拟竞态:next_event_seq 先返回已占用的 1(冲突),重试再返回真实的 2
    seqs = iter([1, 2])
    real = dialect.next_event_seq

    async def flaky(sess, eid):
        try:
            return next(seqs)
        except StopIteration:
            return await real(sess, eid)
    monkeypatch.setattr(dialect, "next_event_seq", flaky)
    e2 = await ev.append_event(session, "p1", EventType.STAGE_CHANGE, {"n": 2})
    assert e2["seq"] == 2  # 冲突后恢复,拿到可用 seq
    assert e2["payload_json"] == {"n": 2}
