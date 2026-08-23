"""Tests for scripts API (剧本创作 + 剧本库)。"""
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
import drama_agent.db.session as db_session
from drama_agent.db.models import Script
from drama_agent.services import script_service as ss


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
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


@pytest.mark.asyncio
async def test_create_script_enqueues_script_start(client):
    from drama_agent.db.enums import JobKind
    captured = {}

    async def _enq(db, kind, entity_id, **kw):
        captured["kind"] = kind
        return {"id": "j1"}

    with patch("drama_agent.api.scripts.job_service.enqueue", AsyncMock(side_effect=_enq)), \
         patch("drama_agent.api.scripts.event_service.append_event", AsyncMock()):
        r = await client.post("/api/scripts",
                              json={"title": "T", "genre": "drama", "source_text": "故事"})
    assert r.status_code == 200
    assert r.json()["id"]
    assert captured["kind"] == JobKind.SCRIPT_START


@pytest.mark.asyncio
async def test_create_script_rejects_invalid_genre(client):
    r = await client.post("/api/scripts", json={"title": "X", "genre": "nope", "source_text": "y"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_and_get_and_crud(client):
    with patch("drama_agent.api.scripts.job_service.enqueue", AsyncMock(return_value={"id": "j1"})), \
         patch("drama_agent.api.scripts.event_service.append_event", AsyncMock()):
        created = (await client.post("/api/scripts",
                   json={"title": "T", "genre": "drama", "source_text": "故事"})).json()
    sid = created["id"]
    lst = (await client.get("/api/scripts")).json()
    assert any(x["id"] == sid for x in lst)
    got = (await client.get(f"/api/scripts/{sid}")).json()
    assert got["id"] == sid
    upd = (await client.put(f"/api/scripts/{sid}", json={"title": "T2", "content": "正文"})).json()
    assert upd["title"] == "T2" and upd["content"] == "正文"
    assert (await client.delete(f"/api/scripts/{sid}")).status_code == 200
    assert (await client.get(f"/api/scripts/{sid}")).status_code == 404


@pytest.mark.asyncio
async def test_start_on_non_draft_returns_409(client):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文", status="completed"))
        await s.commit()
    with patch("drama_agent.api.scripts.job_service.enqueue", AsyncMock(return_value={"id": "j1"})), \
         patch("drama_agent.api.scripts.event_service.append_event", AsyncMock()):
        r = await client.post(f"/api/scripts/{sid}/start")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_resume_not_paused_returns_409(client):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="running"))
        await s.commit()
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ()
    fake.aget_state = AsyncMock(return_value=st)
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)):
        r = await client.post(f"/api/scripts/{sid}/resume", json={"approved": True})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_resume_paused_enqueues_script_resume(client):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    from drama_agent.db.enums import JobKind
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="paused"))
        await s.commit()
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ("screenplay_review",)
    fake.aget_state = AsyncMock(return_value=st)
    captured = {}

    async def _enq(db, kind, entity_id, **kw):
        captured["kind"] = kind
        captured["dedup"] = kw.get("dedup_key")
        return {"id": "j2"}

    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)), \
         patch("drama_agent.api.scripts.job_service.enqueue", AsyncMock(side_effect=_enq)), \
         patch("drama_agent.api.scripts.event_service.append_event", AsyncMock()):
        r = await client.post(f"/api/scripts/{sid}/resume",
                              json={"approved": False, "notes": "改"})
    assert r.status_code == 200
    assert captured["kind"] == JobKind.SCRIPT_RESUME
    assert "screenplay_review" in captured["dedup"]


def _paused_review_graph(current_screenplay: str = "当前正文"):
    """构造一个 aget_state 返回「暂停在 screenplay_review」的假图,
    aupdate_state 记录被调用的参数供断言。"""
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ("screenplay_review",)
    st.values = {"screenplay": current_screenplay}
    fake.aget_state = AsyncMock(return_value=st)
    fake.aupdate_state = AsyncMock()
    return fake


async def _paused_script(sid: str, screenplay: str = "当前正文"):
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(
            id=sid, title="剧", source_text="x", status="paused", llm_model="test-model",
            state_snapshot={"screenplay": screenplay, "paused_at": "screenplay_review"},
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_revise_not_paused_returns_409(client):
    sid = str(uuid.uuid4())
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ()
    fake.aget_state = AsyncMock(return_value=st)
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="running"))
        await s.commit()
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)):
        r = await client.post(
            f"/api/scripts/{sid}/revise",
            json={"messages": [{"role": "user", "content": "改改"}]},
        )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_revise_apply_appends_version_and_writes_back(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid, screenplay="旧正文")
    fake_graph = _paused_review_graph("旧正文")
    fake_turn = AsyncMock(return_value={
        "action": "apply", "reply": "改好了", "screenplay": "新正文", "summary": "改成轻松基调",
    })
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)), \
         patch("drama_agent.api.scripts.screenplay_revise_service.turn", fake_turn):
        r = await client.post(
            f"/api/scripts/{sid}/revise",
            json={"messages": [{"role": "user", "content": "改成轻松基调,确认"}]},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "apply"
    assert body["screenplay"] == "新正文"
    assert body["version_index"] == 1
    fake_graph.aupdate_state.assert_awaited_once_with(
        {"configurable": {"thread_id": sid}}, {"screenplay": "新正文"},
    )

    status = (await client.get(f"/api/scripts/{sid}/status")).json()
    assert status["screenplay_versions"][1]["screenplay"] == "新正文"
    assert status["screenplay_version_current"] == 1


@pytest.mark.asyncio
async def test_revise_ask_does_not_append_version_or_write_back(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid, screenplay="旧正文")
    fake_graph = _paused_review_graph("旧正文")
    fake_turn = AsyncMock(return_value={
        "action": "ask", "reply": "你具体想怎么改?", "screenplay": None, "summary": None,
    })
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)), \
         patch("drama_agent.api.scripts.screenplay_revise_service.turn", fake_turn):
        r = await client.post(
            f"/api/scripts/{sid}/revise", json={"messages": [{"role": "user", "content": "改一下"}]},
        )

    assert r.status_code == 200
    body = r.json()
    assert body == {"action": "ask", "reply": "你具体想怎么改?"}
    fake_graph.aupdate_state.assert_not_awaited()
    status = (await client.get(f"/api/scripts/{sid}/status")).json()
    assert status["screenplay_version_current"] == 0


@pytest.mark.asyncio
async def test_edit_screenplay_appends_manual_version(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid, screenplay="旧正文")
    fake_graph = _paused_review_graph("旧正文")
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)):
        r = await client.post(f"/api/scripts/{sid}/edit_screenplay",
                              json={"screenplay": "手改后的正文"})

    assert r.status_code == 200
    body = r.json()
    assert body["screenplay"] == "手改后的正文"
    assert body["version_index"] == 1
    fake_graph.aupdate_state.assert_awaited_once_with(
        {"configurable": {"thread_id": sid}}, {"screenplay": "手改后的正文"},
    )
    status = (await client.get(f"/api/scripts/{sid}/status")).json()
    assert status["screenplay_versions"][1]["label"] == "手动编辑"


@pytest.mark.asyncio
async def test_edit_screenplay_blank_returns_422(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid)
    fake_graph = _paused_review_graph()
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)):
        r = await client.post(f"/api/scripts/{sid}/edit_screenplay", json={"screenplay": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_screenplay_not_paused_returns_409(client):
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="completed"))
        await s.commit()
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ()
    fake.aget_state = AsyncMock(return_value=st)
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)):
        r = await client.post(f"/api/scripts/{sid}/edit_screenplay",
                              json={"screenplay": "手改后的正文"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_edit_screenplay_state_guard_precedes_body_validation(client):
    """空正文 + 未处于审核态 → 必须 409(状态守卫)而非 422(正文校验):锁住两个判断的先后顺序。"""
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="completed"))
        await s.commit()
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ()
    fake.aget_state = AsyncMock(return_value=st)
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)):
        r = await client.post(f"/api/scripts/{sid}/edit_screenplay", json={"screenplay": "   "})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_revert_switches_current_and_writes_back(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid, screenplay="v0")
    async with db_session.AsyncSessionLocal() as s:
        await ss.append_screenplay_version(
            s, sid, new_screenplay="v1", seed_screenplay="v0", label="改动")
    fake_graph = _paused_review_graph("v1")
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)):
        r = await client.post(f"/api/scripts/{sid}/revert", json={"version_index": 0})

    assert r.status_code == 200
    assert r.json() == {"screenplay": "v0", "version_index": 0}
    fake_graph.aupdate_state.assert_awaited_once_with(
        {"configurable": {"thread_id": sid}}, {"screenplay": "v0"},
    )


@pytest.mark.asyncio
async def test_revert_out_of_range_returns_422(client):
    sid = str(uuid.uuid4())
    await _paused_script(sid)
    fake_graph = _paused_review_graph()
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake_graph)):
        r = await client.post(f"/api/scripts/{sid}/revert", json={"version_index": 99})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_revert_not_paused_returns_409(client):
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", status="completed"))
        await s.commit()
    fake = AsyncMock()
    st = AsyncMock()
    st.next = ()
    fake.aget_state = AsyncMock(return_value=st)
    with patch("drama_agent.api.scripts.get_script_graph", AsyncMock(return_value=fake)):
        r = await client.post(f"/api/scripts/{sid}/revert", json={"version_index": 0})
    assert r.status_code == 409
