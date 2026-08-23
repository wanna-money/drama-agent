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
    orig_e, orig_f = db_session.engine, db_session.AsyncSessionLocal
    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_factory
    # video_actions.resolve_model 需能解析内置视频 model;registry 已收敛为仅 env+DB,
    # 单测不跑 DB seed,故用代码内置声明装一个 registry 单例。
    import drama_agent.provider as provider_pkg
    from drama_agent.provider.registry import ProviderRegistry
    orig_reg = provider_pkg.provider_registry
    provider_pkg.provider_registry = ProviderRegistry(
        builtin=provider_pkg._builtin_providers(), custom_providers=[]
    )

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    from drama_agent.main import app
    from drama_agent.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    provider_pkg.provider_registry = orig_reg
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _seed_root(provider="minimax", resolution="768P"):
    import drama_agent.db.session as db_session
    from drama_agent.services import artifact_service
    async with db_session.AsyncSessionLocal() as s:
        return await artifact_service.create_root(
            s, episode_id="e1", project_id="p1", shot_id="s1", provider=provider,
            model="MiniMax-H3", resolution=resolution, duration=5, task_id="t1",
            video_url="http://v.mp4", local_path=None, prompt_text="hero")


@pytest.mark.asyncio
async def test_list_artifacts(client):
    root = await _seed_root()
    resp = await client.get("/api/episodes/e1/shots/s1/artifacts")
    assert resp.status_code == 200
    arts = resp.json()["artifacts"]
    assert len(arts) == 1
    assert arts[0]["id"] == root["id"]


@pytest.mark.asyncio
async def test_list_actions_for_minimax_768p(client):
    root = await _seed_root()
    resp = await client.get(f"/api/episodes/e1/artifacts/{root['id']}/actions")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()["actions"]}
    assert ids == {"rerun", "regenerate", "upscale"}


@pytest.mark.asyncio
async def test_run_action_creates_child(client):
    from unittest.mock import AsyncMock, patch
    root = await _seed_root()
    fake = AsyncMock()
    fake.supported_actions = ["rerun", "regenerate", "upscale"]
    fake.create_regeneration = AsyncMock(return_value="re-task")
    fake.wait_for_task = AsyncMock(return_value=type("R", (), {
        "status": "succeeded", "video_url": "http://2k.mp4", "last_frame_url": None, "error": None})())
    with patch("drama_agent.services.video_actions.video_service.get_provider", return_value=fake):
        resp = await client.post(f"/api/episodes/e1/artifacts/{root['id']}/actions/upscale", json={})
    assert resp.status_code == 200
    child = resp.json()["artifact"]
    assert child["parent_id"] == root["id"]
    assert child["action"] == "upscale"
    assert child["resolution"] == "2K"


@pytest.mark.asyncio
async def test_run_unknown_action_400(client):
    root = await _seed_root()
    resp = await client.post(f"/api/episodes/e1/artifacts/{root['id']}/actions/nope", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_run_action_wrong_episode_404(client):
    """#2: artifact 属于 e1,用 e2 触发动作 → 404(不能跨集操作他人产物)。"""
    root = await _seed_root()  # episode_id="e1"
    resp = await client.post(f"/api/episodes/e2/artifacts/{root['id']}/actions/upscale", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_actions_wrong_episode_404(client):
    root = await _seed_root()
    resp = await client.get(f"/api/episodes/e2/artifacts/{root['id']}/actions")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_unavailable_action_400(client):
    root = await _seed_root(provider="seedance", resolution="1080p")
    resp = await client.post(f"/api/episodes/e1/artifacts/{root['id']}/actions/upscale", json={})
    assert resp.status_code == 400
