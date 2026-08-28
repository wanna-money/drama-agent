import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch


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


async def _mk_episode(client):
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    pid = (await client.post("/api/projects", json={"title": "P", "story_text": "x"})).json()["id"]
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文"))
        await s.commit()
    ep = await client.post(f"/api/projects/{pid}/episodes",
                           json={"title": "E1", "script_id": sid, "use_keyframes": True,
                                 "keyframe_image_model": "doubao-seedream-3-0-t2i"})
    return pid, ep


@pytest.mark.asyncio
async def test_create_episode_accepts_use_keyframes(client):
    _pid, ep = await _mk_episode(client)
    assert ep.status_code == 200
    # 读回 episode 确认落库
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Episode).where(Episode.id == ep.json()["id"]))).scalar_one()
    assert row.use_keyframes is True
    assert row.keyframe_image_model == "doubao-seedream-3-0-t2i"


@pytest.mark.asyncio
async def test_resume_forwards_assignments_and_regenerate(client):
    _pid, ep = await _mk_episode(client)
    eid = ep.json()["id"]
    captured = {}
    # mock 掉图状态读取(否则命中真 checkpointer sqlite 会挂);伪造停在 look_review
    fake_state = MagicMock()
    fake_state.next = ("look_review",)
    fake_graph = MagicMock()
    fake_graph.aget_state = AsyncMock(return_value=fake_state)
    with patch("drama_agent.api.workflow.get_graph", AsyncMock(return_value=fake_graph)), \
         patch("drama_agent.api.workflow.job_service.enqueue",
               AsyncMock(side_effect=lambda *a, **kw: (captured.update(kw) or {"id": "j1"}))), \
         patch("drama_agent.api.workflow.event_service.append_event", AsyncMock()):
        resp = await client.post(f"/api/episodes/{eid}/workflow/resume", json={
            "approved": True,
            "assignments": {"1": {"林夏": "l2"}},
            "regenerate_shot_ids": ["s1"],
        })
    assert resp.status_code == 200
    payload = captured.get("payload") or {}
    assert payload.get("assignments") == {"1": {"林夏": "l2"}}
    assert payload.get("regenerate_shot_ids") == ["s1"]


@pytest.mark.asyncio
async def test_resume_forwards_edited_negative_prompts(client):
    _pid, ep = await _mk_episode(client)
    eid = ep.json()["id"]
    captured = {}
    fake_state = MagicMock()
    fake_state.next = ("prompts_review",)
    fake_graph = MagicMock()
    fake_graph.aget_state = AsyncMock(return_value=fake_state)
    with patch("drama_agent.api.workflow.get_graph", AsyncMock(return_value=fake_graph)), \
         patch("drama_agent.api.workflow.job_service.enqueue",
               AsyncMock(side_effect=lambda *a, **kw: (captured.update(kw) or {"id": "j1"}))), \
         patch("drama_agent.api.workflow.event_service.append_event", AsyncMock()):
        resp = await client.post(f"/api/episodes/{eid}/workflow/resume", json={
            "approved": True,
            "edited_negative_prompts": {"s1": "no watermark, no blur"},
        })
    assert resp.status_code == 200
    payload = captured.get("payload") or {}
    assert payload.get("edited_negative_prompts") == {"s1": "no watermark, no blur"}


@pytest.mark.asyncio
async def test_status_includes_look_assignments(client):
    _pid, ep = await _mk_episode(client)
    eid = ep.json()["id"]
    resp = await client.get(f"/api/episodes/{eid}/workflow/status")
    assert resp.status_code == 200
    assert "look_assignments" in resp.json()


@pytest.mark.asyncio
async def test_status_includes_pipeline_with_keyframes(client):
    """status 出后端权威的 pipeline;本集 use_keyframes=True → 含关键帧步。"""
    _pid, ep = await _mk_episode(client)  # _mk_episode 建的是 use_keyframes=True 的集
    eid = ep.json()["id"]
    resp = await client.get(f"/api/episodes/{eid}/workflow/status")
    pipeline = resp.json()["pipeline"]
    keys = [s["key"] for s in pipeline["steps"]]
    assert "keyframes" in keys and "looks" in keys
    assert "current" in pipeline


@pytest.mark.asyncio
async def test_status_pipeline_hides_screenplay_steps_for_adapted_episode(client):
    """改编切片集(有 screenplay_versions、无 script_id)不展示剧本三步。

    这类集的剧本是改编时种进去的,runner 直接置 screenplay_approved=True、图直达
    storyboard_director —— 那三步根本不跑,展示出来就是永远走不到的死步骤。
    判据必须与 runner 的入口判定同源(有剧本 = 不走剧本三步),不能只看 script_id。
    """
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from drama_agent.services import episode_service
    pid = (await client.post("/api/projects", json={"title": "P"})).json()["id"]
    async with db_session.AsyncSessionLocal() as s:
        ep = await episode_service.create(
            s, project_id=pid, title="改编集", script_id=None,
            llm_model="m", video_provider="v", video_model="", resolution="768P",
            seed_screenplay="分集剧本正文")
    eid = ep["id"]
    async with db_session.AsyncSessionLocal() as s:
        from sqlalchemy import select as _select
        row = (await s.execute(_select(Episode).where(Episode.id == eid))).scalar_one()
        assert row.script_id is None and row.screenplay_versions   # 前提:改编切片集的形状
    assert uuid.UUID(eid)

    keys = [s["key"] for s in
            (await client.get(f"/api/episodes/{eid}/workflow/status")).json()["pipeline"]["steps"]]
    assert "analysis" not in keys
    assert "screenplay" not in keys
    assert "screenplay_review" not in keys
    assert "storyboard" in keys                                   # 制作段仍在
