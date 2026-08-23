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
                     content="正文" if script_status == "completed" else None,
                     status=script_status))
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
async def test_create_episode_rejects_uncompleted_script(client):
    pid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed(pid, sid, "created")
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "E1", "script_id": sid, "video_provider": "seedance"})
    assert r.status_code == 409


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
