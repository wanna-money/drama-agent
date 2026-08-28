"""Tests for scripts API —— 剧本库降为只读复用素材后的接口面。

剧本创作/审核/生成/版本已搬到 Episode(见 workflow.py 的 /episodes/{id}/screenplay/*),
本文件只覆盖剧本库剩下的:从剧集存入、列表(含归属标注)、详情、删除,以及旧端点已 404。
"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
import drama_agent.db.session as db_session
from drama_agent.db.models import Episode, Project, Script


@pytest.fixture
async def client():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    original_engine = db_session.engine
    original_factory = db_session.AsyncSessionLocal
    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    from drama_agent.main import app
    from drama_agent.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    db_session.engine = original_engine
    db_session.AsyncSessionLocal = original_factory
    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _seed_episode_with_screenplay(eid, pid, screenplay, *, raw_input="故事原文"):
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id=pid, title="作品", genre="drama"))
        s.add(Episode(
            id=eid, project_id=pid, episode_number=1, title="第 1 集", script_id=None,
            raw_input=raw_input,
            state_snapshot={"screenplay": screenplay,
                            "story_analysis": {"genre": "romance"}} if screenplay else {},
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_save_from_episode_creates_reusable_script(client):
    """某集有正文 → 存入剧本库:落 content/来源/故事分析,归属跟随该集所属作品。"""
    eid, pid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_episode_with_screenplay(eid, pid, "内景 办公室 - 夜\n林晚敲着键盘。")
    r = await client.post("/api/scripts", json={"episode_id": eid})
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "内景 办公室 - 夜\n林晚敲着键盘。"
    assert body["project_id"] == pid
    assert body["genre"] == "romance"        # 取自 story_analysis
    assert body["source_text"] == "故事原文"
    # 真的落库:列表里能查到
    lst = (await client.get("/api/scripts")).json()
    assert any(x["id"] == body["id"] for x in lst)


@pytest.mark.asyncio
async def test_save_from_episode_without_screenplay_409(client):
    """该集还没有剧本正文 → 不能存入。"""
    eid, pid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_episode_with_screenplay(eid, pid, "")
    r = await client.post("/api/scripts", json={"episode_id": eid})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_list_marks_ownership_and_get_delete(client):
    """列表带 project_title(散稿为 None);get/delete 正常。"""
    owned, loose = str(uuid.uuid4()), str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id="pj", title="作品甲", genre="drama"))
        s.add(Script(id=owned, title="归属剧本", content="正文", project_id="pj"))
        s.add(Script(id=loose, title="散稿", content="正文", project_id=None))
        await s.commit()
    rows = {r["id"]: r for r in (await client.get("/api/scripts")).json()}
    assert rows[owned]["project_title"] == "作品甲"
    assert rows[loose]["project_title"] is None
    assert (await client.get(f"/api/scripts/{owned}")).status_code == 200
    assert (await client.delete(f"/api/scripts/{loose}")).status_code == 200
    assert (await client.get(f"/api/scripts/{loose}")).status_code == 404


@pytest.mark.asyncio
async def test_removed_script_creation_endpoints_are_gone(client):
    """剧本创作/审核端点已移除:老路径不再存在(405/404,总之非 2xx)。"""
    for path in ("/api/scripts/x/start", "/api/scripts/x/retry",
                 "/api/scripts/x/resume", "/api/scripts/x/revise",
                 "/api/scripts/x/edit_screenplay", "/api/scripts/x/revert"):
        r = await client.post(path, json={})
        assert r.status_code >= 400
    assert (await client.get("/api/scripts/x/status")).status_code >= 400
