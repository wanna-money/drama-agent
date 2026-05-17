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


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_project(client):
    resp = await client.post("/api/projects", json={
        "title": "Test Drama",
        "raw_input": "A story about a hero.",
        "genre": "drama",
        "video_provider": "seedance",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Drama"
    assert data["status"] == "created"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_projects(client):
    await client.post("/api/projects", json={
        "title": "List Test",
        "raw_input": "Story content",
    })
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
async def test_delete_project(client):
    create_resp = await client.post("/api/projects", json={
        "title": "To Delete",
        "raw_input": "Some story",
    })
    project_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/projects/{project_id}")
    assert del_resp.status_code == 200

    get_resp = await client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 404
