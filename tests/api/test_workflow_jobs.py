import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base
    te = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tf = async_sessionmaker(te, expire_on_commit=False)
    async with te.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig_e, orig_f = db_session.engine, db_session.AsyncSessionLocal
    db_session.engine, db_session.AsyncSessionLocal = te, tf

    async def ogd():
        async with tf() as s:
            yield s
    from drama_agent.main import app
    from drama_agent.db.session import get_db
    app.dependency_overrides[get_db] = ogd
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await te.dispose()


async def _new_episode(client) -> str:
    """建项目 + 一集(引用 completed Script),返回 episode_id。"""
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    pid = (await client.post("/api/projects", json={"title": "t"})).json()["id"]
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文", status="completed"))
        await s.commit()
    r = await client.post(f"/api/projects/{pid}/episodes",
                          json={"title": "e", "script_id": sid})
    return r.json()["id"]


@pytest.mark.asyncio
async def test_start_enqueues_and_sets_queued(client):
    eid = await _new_episode(client)
    r = await client.post(f"/api/episodes/{eid}/workflow/start")
    assert r.status_code == 200 and "job_id" in r.json()
    st = await client.get(f"/api/episodes/{eid}/workflow/status")
    assert st.json()["db_status"] == "queued"


@pytest.mark.asyncio
async def test_start_guarded_when_not_created(client):
    eid = await _new_episode(client)
    await client.post(f"/api/episodes/{eid}/workflow/start")  # → queued
    r2 = await client.post(f"/api/episodes/{eid}/workflow/start")
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_events_endpoint(client):
    eid = await _new_episode(client)
    await client.post(f"/api/episodes/{eid}/workflow/start")  # 产 queued 事件
    r = await client.get(f"/api/episodes/{eid}/workflow/events?after_seq=0")
    assert r.status_code == 200 and isinstance(r.json()["events"], list)
    assert len(r.json()["events"]) >= 1


@pytest.mark.asyncio
async def test_start_not_found(client):
    r = await client.post("/api/episodes/nope/workflow/start")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_status_on_created_episode(client):
    eid = await _new_episode(client)
    r = await client.get(f"/api/episodes/{eid}/workflow/status")
    assert r.status_code == 200
    assert r.json()["db_status"] == "created"


@pytest.mark.asyncio
async def test_status_not_found(client):
    r = await client.get("/api/episodes/nope/workflow/status")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resume_guarded_when_not_paused(client):
    eid = await _new_episode(client)
    # 未开始的集图未停在 interrupt → resume 应 409
    r = await client.post(f"/api/episodes/{eid}/workflow/resume", json={"approved": True})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_status_returns_paused_at_from_snapshot(client):
    """status 暴露 snapshot.paused_at,供前端判断停在哪个审核步。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    eid = await _new_episode(client)
    async with db_session.AsyncSessionLocal() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == eid))).scalar_one()
        ep.status = "paused"
        ep.state_snapshot = {"current_stage": "screenplay_written", "paused_at": "screenplay_review"}
        await s.commit()
    r = await client.get(f"/api/episodes/{eid}/workflow/status")
    body = r.json()
    assert body["db_status"] == "paused"
    assert body["paused_at"] == "screenplay_review"
