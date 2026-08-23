"""成本投影:status / 列表 / 详情下发估算成本,provider 模型可读写单价。"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport


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


async def _seed_episode(*, status: str = "running", stage: str | None = None) -> tuple[str, str]:
    """建一条 project+script+episode,返回 (project_id, episode_id)。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project, Episode, Script

    pid, eid, sid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Project(id=pid, title="剧", genre="drama"))
        s.add(Script(id=sid, title="剧", source_text="x", content="正文", status="completed"))
        s.add(Episode(
            id=eid, project_id=pid, episode_number=1, title="E", script_id=sid,
            status=status, use_keyframes=False,
            state_snapshot={"current_stage": stage} if stage else None,
        ))
        await s.commit()
    return pid, eid


@pytest.mark.asyncio
async def test_status_includes_cost(client):
    """status 下发成本汇总字段(总额/未定价标记/token 数/按类别)。"""
    _pid, eid = await _seed_episode()
    agg = {"by_node": {}, "by_kind": {"llm": 1.2}, "total": 1.2,
           "tokens_total": 1000, "unpriced": False}
    with patch("drama_agent.api.workflow.cost_service.aggregate_entity",
               AsyncMock(return_value=agg)):
        r = await client.get(f"/api/episodes/{eid}/workflow/status")
    assert r.status_code == 200
    body = r.json()
    assert body["cost_total"] == 1.2
    assert body["cost_unpriced"] is False
    assert body["cost_tokens_total"] == 1000
    assert body["cost_by_kind"] == {"llm": 1.2}


@pytest.mark.asyncio
async def test_status_pipeline_step_cost_maps_stage_to_step(client):
    """by_node 的键是 current_stage,须按 PipelineStep.stages 归并到 step key 上。

    这是 T6 的关键契约:记账的 node 词表(current_stage)与 step key 词表不同,
    映射错了前端就挂不上成本。多个 stage 落同一步时须相加。
    """
    _pid, eid = await _seed_episode()
    agg = {
        "by_node": {
            "story_analyzed": 0.5,          # → step "analysis"
            "screenplay_written": 1.0,      # → step "screenplay"
            "screenplay_revision_requested": 0.25,  # 同属 "screenplay",须累加
            "unknown_stage": 9.0,           # 不属任何步 → 丢弃,不得凭空造 step
        },
        "by_kind": {}, "total": 10.75, "tokens_total": 0, "unpriced": False,
    }
    with patch("drama_agent.api.workflow.cost_service.aggregate_entity",
               AsyncMock(return_value=agg)):
        r = await client.get(f"/api/episodes/{eid}/workflow/status")
    steps = {s["key"]: s for s in r.json()["pipeline"]["steps"]}
    assert steps["analysis"]["cost"] == 0.5
    assert steps["screenplay"]["cost"] == 1.25
    assert "cost" not in steps["storyboard"]  # 无记账的步不挂 cost 字段


@pytest.mark.asyncio
async def test_project_list_and_detail_cost(client):
    """项目列表/详情投影带 cost_total + cost_unpriced。"""
    pid, _eid = await _seed_episode()
    with patch("drama_agent.api.projects.cost_service.project_total",
               AsyncMock(return_value={"total": 3.5, "unpriced": True})):
        lst = await client.get("/api/projects")
        detail = await client.get(f"/api/projects/{pid}")
    item = next(p for p in lst.json() if p["id"] == pid)
    assert item["cost_total"] == 3.5
    assert item["cost_unpriced"] is True
    assert detail.json()["cost_total"] == 3.5


@pytest.mark.asyncio
async def test_episode_detail_cost(client):
    """集详情投影带 cost_total。"""
    pid, eid = await _seed_episode()
    agg = {"by_node": {}, "by_kind": {}, "total": 2.25,
           "tokens_total": 40, "unpriced": False}
    with patch("drama_agent.api.episodes.cost_service.aggregate_entity",
               AsyncMock(return_value=agg)):
        r = await client.get(f"/api/projects/{pid}/episodes/{eid}")
    assert r.json()["cost_total"] == 2.25


@pytest.mark.asyncio
async def test_provider_model_cost_roundtrip(client):
    """provider 模型的 cost 单价写入后能原样读回(前端填价依赖此)。"""
    body = {
        "provider_id": "px", "label": "PX", "kind": "llm", "protocol": "openai-compat",
        "api_key": "k",
        "models": [{"id": "mx", "label": "MX", "kind": "llm",
                    "cost": {"input": 2.0, "output": 8.0}}],
    }
    with patch("drama_agent.api.providers._rebuild_safe", AsyncMock()):
        created = await client.post("/api/providers", json=body)
    assert created.status_code == 200, created.text
    got = await client.get("/api/providers/px")
    assert got.json()["models"][0]["cost"]["input"] == 2.0
    assert got.json()["models"][0]["cost"]["output"] == 8.0


@pytest.mark.asyncio
async def test_provider_model_rejects_bad_cost(client):
    """cost 里的非法值应被模型校验拒掉(422),不能静默存进库。"""
    body = {
        "provider_id": "pbad", "label": "PB", "kind": "llm", "protocol": "openai-compat",
        "models": [{"id": "mb", "label": "MB", "kind": "llm",
                    "cost": {"input": "not-a-number"}}],
    }
    with patch("drama_agent.api.providers._rebuild_safe", AsyncMock()):
        r = await client.post("/api/providers", json=body)
    assert r.status_code == 422
