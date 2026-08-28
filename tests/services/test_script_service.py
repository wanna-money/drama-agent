"""script_service 测试:剧本库降为只读复用素材后的服务面。

版本树/审核/生成状态已搬到 episode_service(见 test_episode_service_versions.py),
本文件只覆盖 create / list_scripts(含归属) / get / delete / create_from_episode。
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


@pytest.mark.asyncio
async def test_create_list_get_delete(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", genre="drama", source_text="故事", content="正文")
    sid = r["id"]
    assert r["content"] == "正文"
    assert any(x["id"] == sid for x in await ss.list_scripts(session))
    assert (await ss.get(session, sid))["id"] == sid
    assert await ss.delete(session, sid) is True
    assert await ss.get(session, sid) is None


@pytest.mark.asyncio
async def test_list_filter_by_project_and_ownership_title(session):
    from drama_agent.db.models import Project
    from drama_agent.services import script_service as ss
    session.add(Project(id="p1", title="作品甲", genre="drama"))
    await session.commit()
    await ss.create(session, title="A", source_text="x", content="c", project_id="p1")
    await ss.create(session, title="B", source_text="y", content="c")  # 散稿
    # project 过滤只返回该作品的
    assert len(await ss.list_scripts(session, project_id="p1")) == 1
    # 不过滤时,归属标注:有作品的带标题,散稿为 None
    rows = await ss.list_scripts(session)
    by_title = {r["title"]: r for r in rows}
    assert by_title["A"]["project_title"] == "作品甲"
    assert by_title["B"]["project_title"] is None


@pytest.mark.asyncio
async def test_create_from_episode_pulls_screenplay_and_analysis(session):
    from drama_agent.db.models import Episode
    from drama_agent.services import script_service as ss
    eid = str(uuid.uuid4())
    session.add(Episode(
        id=eid, project_id="pj", episode_number=1, title="第 1 集", script_id=None,
        raw_input="原始故事",
        state_snapshot={"screenplay": "内景 房间 - 日", "story_analysis": {"genre": "thriller"}},
    ))
    await session.commit()
    r = await ss.create_from_episode(session, eid)
    assert r["content"] == "内景 房间 - 日"
    assert r["genre"] == "thriller"
    assert r["source_text"] == "原始故事"
    assert r["project_id"] == "pj"


@pytest.mark.asyncio
async def test_create_from_episode_empty_screenplay_returns_none(session):
    from drama_agent.db.models import Episode
    from drama_agent.services import script_service as ss
    eid = str(uuid.uuid4())
    session.add(Episode(id=eid, project_id="pj", episode_number=1, title="E", script_id=None,
                        state_snapshot={}))
    await session.commit()
    assert await ss.create_from_episode(session, eid) is None
    assert await ss.create_from_episode(session, "no-such") is None
