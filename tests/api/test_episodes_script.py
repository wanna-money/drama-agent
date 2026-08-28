"""Episode 引用 completed Script(script_id)建集;未 completed → 409。"""
import uuid
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig_e, orig_f = db_session.engine, db_session.AsyncSessionLocal
    db_session.engine = eng
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    from drama_agent.main import app
    from drama_agent.db.session import get_db

    async def override():
        async with db_session.AsyncSessionLocal() as s:
            yield s
    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await eng.dispose()


async def _seed(project_id, script_id, script_status):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project, Script
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id=project_id, title="P", genre="drama"))
        s.add(Script(id=script_id, title="剧", source_text="x",
                     content="正文" if script_status == "completed" else None))
        await s.commit()


async def _seed_project(project_id):
    """只建项目(不建剧本),用于"从故事直接建集"路径。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id=project_id, title="P", genre="drama"))
        await s.commit()


@pytest.mark.asyncio
async def test_create_episode_from_completed_script(client):
    pid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(pid, sid, "completed")
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "E1", "script_id": sid, "video_provider": "seedance"})
    assert r.status_code == 200
    assert r.json()["script_id"] == sid


@pytest.mark.asyncio
async def test_create_episode_rejects_script_without_content(client):
    """复用剧本建集不再看 status(该列已删),只要求 content 非空 → 空正文的剧本 409。"""
    pid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(pid, sid, "created")  # content=None
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "E1", "script_id": sid, "video_provider": "seedance"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_episode_from_story_without_script(client):
    """从故事建集:不传 script_id,raw_input 落库,script_id 为 None。

    这是"输入故事 → 直接建集"动线的核心 —— 原来这个 tab 建的是 Script,用户被踢去剧本库。
    """
    pid = str(uuid.uuid4())
    await _seed_project(pid)
    eid_resp = await client.post(f"/api/projects/{pid}/episodes", json={
        "title": "从故事开始", "raw_input": "深夜加班的女孩收到陌生短信。",
        "target_seconds": 90,
    })
    assert eid_resp.status_code == 200
    body = eid_resp.json()
    assert body["script_id"] is None
    assert body["raw_input"] == "深夜加班的女孩收到陌生短信。"
    assert body["target_seconds"] == 90

    # 从库中重读,确认真的落库了(不是只存在于响应里)
    got = (await client.get(f"/api/projects/{pid}/episodes/{body['id']}")).json()
    assert got["raw_input"] == "深夜加班的女孩收到陌生短信。"
    assert got["target_seconds"] == 90


@pytest.mark.asyncio
async def test_create_episode_from_script_still_works(client):
    """复用剧本建集:传 script_id 仍有 content 的非空校验,但不再要求 completed。"""
    pid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(pid, sid, "completed")
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "复用", "script_id": sid})
    assert r.status_code == 200
    assert r.json()["script_id"] == sid


@pytest.mark.asyncio
async def test_create_episode_requires_story_or_script(client):
    """既不传 script_id 也不传 raw_input → 422(无从下手)。"""
    pid = str(uuid.uuid4())
    await _seed_project(pid)
    r = await client.post(f"/api/projects/{pid}/episodes", json={"title": "空"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_episode_rejects_missing_script(client):
    pid = str(uuid.uuid4())
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id=pid, title="P", genre="drama"))
        await s.commit()
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "E1", "script_id": "no-such",
                                "video_provider": "seedance"})
    assert r.status_code == 409


# ── 开拍前编辑(PATCH) ────────────────────────────────────────────────
async def _make_story_episode(client, status: str = "created") -> tuple[str, str]:
    """建一集"从故事开始"的集,并把状态置成 status。返回 (project_id, episode_id)。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    pid = str(uuid.uuid4())
    await _seed_project(pid)
    eid = (await client.post(f"/api/projects/{pid}/episodes", json={
        "title": "原标题", "raw_input": "原始故事", "target_seconds": 120,
    })).json()["id"]
    if status != "created":
        async with db_session.AsyncSessionLocal() as s:
            ep = (await s.execute(select(Episode).where(Episode.id == eid))).scalar_one()
            ep.status = status
            await s.commit()
    return pid, eid


@pytest.mark.asyncio
async def test_patch_updates_story_before_start(client):
    """开拍前改故事内容要真的落库 —— 只断响应体会读到内存 ORM 对象,即使没落库也显示正确。"""
    pid, eid = await _make_story_episode(client)
    r = await client.patch(f"/api/projects/{pid}/episodes/{eid}",
                           json={"raw_input": "改过的故事", "title": "新标题"})
    assert r.status_code == 200
    got = (await client.get(f"/api/projects/{pid}/episodes/{eid}")).json()
    assert got["raw_input"] == "改过的故事"
    assert got["title"] == "新标题"


@pytest.mark.asyncio
async def test_patch_only_touches_given_fields(client):
    """未传的字段不得被覆盖 —— 否则改标题会顺手把故事清空。"""
    pid, eid = await _make_story_episode(client)
    await client.patch(f"/api/projects/{pid}/episodes/{eid}", json={"title": "只改标题"})
    got = (await client.get(f"/api/projects/{pid}/episodes/{eid}")).json()
    assert got["title"] == "只改标题"
    assert got["raw_input"] == "原始故事"
    assert got["target_seconds"] == 120


@pytest.mark.asyncio
async def test_patch_rejected_after_start(client):
    """已开拍 → 409。故事分析与剧本都由这段原文推导而来,改它会让产出与源头不符。"""
    pid, eid = await _make_story_episode(client, status="running")
    r = await client.patch(f"/api/projects/{pid}/episodes/{eid}",
                           json={"raw_input": "偷偷改"})
    assert r.status_code == 409
    got = (await client.get(f"/api/projects/{pid}/episodes/{eid}")).json()
    assert got["raw_input"] == "原始故事"   # 守卫拒绝后不得有部分写入


@pytest.mark.asyncio
async def test_patch_rejects_blank_story_for_story_episode(client):
    """从故事开始的集靠这段原文起跑,清空它会让开拍无输入可用 → 422。"""
    pid, eid = await _make_story_episode(client)
    r = await client.patch(f"/api/projects/{pid}/episodes/{eid}", json={"raw_input": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_cross_project_is_404(client):
    """集不属于该项目时 404(防跨项目误改)。"""
    pid, eid = await _make_story_episode(client)
    other = str(uuid.uuid4())
    await _seed_project(other)
    r = await client.patch(f"/api/projects/{other}/episodes/{eid}", json={"title": "越权"})
    assert r.status_code == 404
