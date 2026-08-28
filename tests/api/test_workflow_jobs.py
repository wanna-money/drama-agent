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
        s.add(Script(id=sid, title="剧", source_text="x", content="正文"))
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


async def _mark_paused(client, snapshot: dict | None = None) -> str:
    """建一集并把投影置成"暂停在剧本审核"。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    eid = await _new_episode(client)
    async with db_session.AsyncSessionLocal() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == eid))).scalar_one()
        ep.status = "paused"
        ep.state_snapshot = snapshot or {
            "current_stage": "screenplay_written", "paused_at": "screenplay_review"}
        await s.commit()
    return eid


class _FakeGraph:
    """aget_state 只回 next —— status 的暂停点核对只看这个。"""
    def __init__(self, next_nodes):
        self._next = tuple(next_nodes)

    async def aget_state(self, _config):
        from types import SimpleNamespace
        return SimpleNamespace(next=self._next, values={})


@pytest.fixture
def graph_singleton(monkeypatch):
    """直接替换图单例。不能让 status 走 get_graph() 惰性建连(见 _graph_still_paused 注释),
    所以测试也按同一契约注入,而不是依赖测试执行顺序里恰好有没有别的用例初始化过图。"""
    from drama_agent.workflow import graph as graph_mod

    def _set(next_nodes):
        monkeypatch.setattr(graph_mod, "_graph", _FakeGraph(next_nodes))
    return _set


@pytest.mark.asyncio
async def test_status_returns_paused_at_when_graph_confirms(client, graph_singleton):
    """图确认仍停在该中断点时,status 如实下发 paused_at,供前端渲染审核面板。"""
    graph_singleton(["screenplay_review"])
    eid = await _mark_paused(client)
    r = await client.get(f"/api/episodes/{eid}/workflow/status")
    body = r.json()
    assert body["db_status"] == "paused"
    assert body["paused_at"] == "screenplay_review"
    assert body["state_lost"] is False


@pytest.mark.asyncio
async def test_status_clears_paused_at_when_graph_has_no_state(client, graph_singleton):
    """投影说暂停、图里却没有状态(checkpoint 被换/删,或跑该集的是已消失的旧进程)→
    必须清掉 paused_at 并标 state_lost。

    不清的话前端会渲染出可点的审核面板,而 resume/revise 的守卫读活图必然 409 ——
    用户点下去才知道状态没了。删掉这条就放走那个"看起来能操作、点了才报错"的回归。
    """
    graph_singleton([])          # 图里没有任何待执行节点 = 没有暂停状态
    eid = await _mark_paused(client)
    r = await client.get(f"/api/episodes/{eid}/workflow/status")
    body = r.json()
    assert body["paused_at"] is None
    assert body["state_lost"] is True


@pytest.mark.asyncio
async def test_status_keeps_paused_at_when_graph_unavailable(client, monkeypatch):
    """图未初始化(读不到)时不下"已丢失"的结论 —— 那是暂时故障,不是状态没了。
    误判成丢失会让一个其实还能继续的集显示成必须重跑。"""
    from drama_agent.workflow import graph as graph_mod
    monkeypatch.setattr(graph_mod, "_graph", None)
    eid = await _mark_paused(client)
    r = await client.get(f"/api/episodes/{eid}/workflow/status")
    body = r.json()
    assert body["paused_at"] == "screenplay_review"
    assert body["state_lost"] is False
