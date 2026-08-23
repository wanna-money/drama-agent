"""scripts API 测试:创建剧本时透传并持久化 llm_model。"""
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


@pytest.mark.asyncio
async def test_create_script_persists_llm_model(client):
    r = await client.post("/api/scripts", json={
        "title": "T", "genre": "drama", "source_text": "once upon a time",
        "llm_model": "deepseek-v4-pro",
    })
    assert r.status_code == 200
    sid = r.json()["id"]
    got = await client.get(f"/api/scripts/{sid}")
    assert got.json()["llm_model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_status_surfaces_screenplay_from_snapshot_while_paused(client):
    """审核暂停时正文尚未落 Script 行,get_status 应从 state_snapshot 回落透出 —— 否则前端看不到
    已生成的剧本(误判"无内容/生成中断")。删掉这层回落该 bug 立即复现。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    from sqlalchemy import select
    sid = (await client.post("/api/scripts", json={
        "title": "T", "genre": "drama", "source_text": "x"})).json()["id"]
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Script).where(Script.id == sid))).scalar_one()
        row.status = "paused"
        row.content = None
        row.story_analysis = None
        row.state_snapshot = {"paused_at": "screenplay_review",
                              "screenplay": "SCENE 1 内景", "story_analysis": {"genre": "drama"}}
        await s.commit()
    st = (await client.get(f"/api/scripts/{sid}/status")).json()
    assert st["paused_at"] == "screenplay_review"
    assert st["content"] == "SCENE 1 内景"                  # 正文从快照回落
    assert st["story_analysis"] == {"genre": "drama"}       # 故事分析从快照回落


async def _make_stuck_script(client, status: str) -> str:
    """建剧本后把它直接改成给定 status + 陈旧产物,模拟"卡住/失败"态。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    from sqlalchemy import select
    sid = (await client.post("/api/scripts", json={
        "title": "T", "genre": "drama", "source_text": "x"})).json()["id"]
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Script).where(Script.id == sid))).scalar_one()
        row.status = status
        row.content = "陈旧正文"
        row.error_message = "boom"
        await s.commit()
    return sid


@pytest.mark.asyncio
async def test_retry_resets_content_and_rearms_job(client, monkeypatch):
    """重试:清 checkpointer 线程 + 清空旧产物/错误 + 状态置 queued + 重新武装 SCRIPT_START。"""
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy import select
    import drama_agent.api.scripts as scripts_api
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script, Job

    sid = await _make_stuck_script(client, "paused")
    fake_graph = MagicMock()
    fake_graph.checkpointer.adelete_thread = AsyncMock()
    monkeypatch.setattr(scripts_api, "get_script_graph", AsyncMock(return_value=fake_graph))

    resp = await client.post(f"/api/scripts/{sid}/retry")
    assert resp.status_code == 200
    fake_graph.checkpointer.adelete_thread.assert_awaited_once_with(sid)  # 线程被重置

    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Script).where(Script.id == sid))).scalar_one()
        assert row.content is None and row.error_message is None   # 旧产物清空
        assert row.status == "queued"                              # 置排队(可轮询)
        jobs = (await s.execute(
            select(Job).where(Job.episode_id == sid, Job.kind == "script_start"))).scalars().all()
        assert len(jobs) == 1 and jobs[0].status == "queued"       # SCRIPT_START 重新武装


@pytest.mark.asyncio
async def test_retry_rejected_when_running(client, monkeypatch):
    """运行中(running/queued)的剧本不允许重试(避免打断在跑的生成)。"""
    from unittest.mock import AsyncMock, MagicMock
    import drama_agent.api.scripts as scripts_api

    sid = await _make_stuck_script(client, "running")
    fake_graph = MagicMock()
    fake_graph.checkpointer.adelete_thread = AsyncMock()
    monkeypatch.setattr(scripts_api, "get_script_graph", AsyncMock(return_value=fake_graph))

    resp = await client.post(f"/api/scripts/{sid}/retry")
    assert resp.status_code == 409
    fake_graph.checkpointer.adelete_thread.assert_not_awaited()   # 运行中不重置线程
