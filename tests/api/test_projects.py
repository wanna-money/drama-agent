"""Tests for FastAPI project endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client():
    """Create test client with in-memory DB and proper table init."""
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base

    # Override engine and session to use in-memory SQLite for tests
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Monkey-patch session module
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

    # Restore
    db_session.engine = original_engine
    db_session.AsyncSessionLocal = original_factory
    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _new_script() -> str:
    """建一条 completed Script,返回其 id(建集需引用)。"""
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文"))
        await s.commit()
    return sid


async def _post_episode(client, project_id: str, **fields):
    """建集:自动挂一条 completed Script。"""
    return await client.post(f"/api/projects/{project_id}/episodes",
                             json={"script_id": await _new_script(), **fields})


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_project(client):
    resp = await client.post("/api/projects", json={"title": "Test Drama", "genre": "drama"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Drama"
    assert data["genre"] == "drama"
    assert data["status"] == "empty"  # 新项目还没有集
    assert "id" in data


@pytest.mark.asyncio
async def test_create_project_rejects_invalid_genre(client):
    """非法 genre 由枚举校验拦为 422,脏值不入库(收敛后的边界守卫)。"""
    resp = await client.post("/api/projects", json={"title": "X", "genre": "not-a-genre"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_projects(client):
    await client.post("/api/projects", json={"title": "List Test"})
    resp = await client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert isinstance(projects, list)
    assert any(p["title"] == "List Test" for p in projects)


@pytest.mark.asyncio
async def test_get_project_not_found(client):
    resp = await client.get("/api/projects/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_project_includes_episodes(client):
    pid = (await client.post("/api/projects", json={"title": "With Eps"})).json()["id"]
    await _post_episode(client, pid, title="第1集", resolution="2K")
    got = (await client.get(f"/api/projects/{pid}")).json()
    assert len(got["episodes"]) == 1
    assert got["episodes"][0]["resolution"] == "2K"
    # 有一集在 created 态 → 项目状态聚合应非 empty
    assert got["status"] != "empty"


@pytest.mark.asyncio
async def test_delete_project_cascades(client):
    """删项目应级联清理其下 episodes(及 jobs/events/artifacts)。"""
    pid = (await client.post("/api/projects", json={"title": "To Delete"})).json()["id"]
    eid = (await _post_episode(client, pid, title="e")).json()["id"]

    del_resp = await client.delete(f"/api/projects/{pid}")
    assert del_resp.status_code == 200

    assert (await client.get(f"/api/projects/{pid}")).status_code == 404
    # 该集也应随项目级联删除
    assert (await client.get(f"/api/episodes/{eid}/workflow/status")).status_code == 404


@pytest.mark.asyncio
async def test_episode_carries_resolution(client):
    """分辨率是集级属性,建集时设定并回读。"""
    pid = (await client.post("/api/projects", json={"title": "T"})).json()["id"]
    ep = (await _post_episode(client, pid, title="e",
                              video_provider="minimax", resolution="2K")).json()
    assert ep["resolution"] == "2K"
    got = (await client.get(f"/api/projects/{pid}/episodes/{ep['id']}")).json()
    assert got["resolution"] == "2K"


@pytest.mark.asyncio
async def test_episode_resolution_defaults(client):
    pid = (await client.post("/api/projects", json={"title": "T"})).json()["id"]
    ep = (await _post_episode(client, pid, title="e")).json()
    assert ep["resolution"] == "768P"


@pytest.mark.asyncio
async def test_episode_number_auto_increment(client):
    pid = (await client.post("/api/projects", json={"title": "T"})).json()["id"]
    e1 = (await _post_episode(client, pid, title="a")).json()
    e2 = (await _post_episode(client, pid, title="b")).json()
    assert e1["episode_number"] == 1 and e2["episode_number"] == 2
