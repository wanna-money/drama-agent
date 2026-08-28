"""Episode 上的剧本版本树:append/revert 语义(逻辑从 script_service 搬来,实体换成 Episode)。

拦的是版本树搬家后语义走样:初稿懒种、越界报错、缺实体返回 None。
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
    await eng.dispose()


async def _make_episode(session) -> str:
    from drama_agent.db.models import Episode
    eid = str(uuid.uuid4())
    session.add(Episode(id=eid, project_id="p1", episode_number=1, title="T", script_id=None))
    await session.commit()
    return eid


@pytest.mark.asyncio
async def test_append_seeds_draft_then_appends(session):
    """首次 append 时,version 0 由 seed_screenplay 合成「初稿」,新内容落在 index 1。"""
    from drama_agent.services import episode_service as es
    eid = await _make_episode(session)
    v = await es.append_screenplay_version(
        session, eid, new_screenplay="改写后", seed_screenplay="原文", label="AI 改写")
    assert v["version_index"] == 1
    assert v["versions_len"] == 2


@pytest.mark.asyncio
async def test_set_current_version_switches_and_out_of_range_raises(session):
    from drama_agent.services import episode_service as es
    eid = await _make_episode(session)
    await es.append_screenplay_version(
        session, eid, new_screenplay="v2", seed_screenplay="v1", label="改写")
    out = await es.set_current_version(session, eid, 0)
    assert out["screenplay"] == "v1"
    with pytest.raises(IndexError):
        await es.set_current_version(session, eid, 99)


@pytest.mark.asyncio
async def test_append_on_missing_episode_returns_none(session):
    from drama_agent.services import episode_service as es
    assert await es.append_screenplay_version(
        session, "no-such-id", new_screenplay="x", seed_screenplay="y", label="l") is None
