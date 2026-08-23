"""P3 tests: /api/providers CRUD + 校验 + 掩码 + 内置只读 + 写后联动 config models。"""
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
    # 恢复全局 registry(写测试会 rebuild)
    import drama_agent.provider as provider_pkg
    provider_pkg.provider_registry = provider_pkg.build_registry()
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await te.dispose()


def _body(**kw):
    b = {
        "provider_id": "mycorp", "label": "私有", "kind": "llm", "protocol": "openai-compat",
        "base_url": "https://x/v1", "api_key": "sk-secret-1234",
        "models": [{"id": "qwen-max", "label": "Qwen Max", "kind": "llm"}],
    }
    b.update(kw)
    return b


@pytest.mark.asyncio
async def test_create_lists_masked_and_get_returns_real_key(client):
    r = await client.post("/api/providers", json=_body())
    assert r.status_code == 200
    assert r.json()["api_key"] == "***1234"          # 创建返回掩码
    lst = (await client.get("/api/providers")).json()
    mine = next(p for p in lst if p["provider_id"] == "mycorp")
    assert mine["api_key"] == "***1234" and mine["builtin"] is False
    # 详情返回真值 key(供编辑)
    got = (await client.get("/api/providers/mycorp")).json()
    assert got["api_key"] == "sk-secret-1234"


@pytest.mark.asyncio
async def test_post_conflict_existing_409(client):
    await client.post("/api/providers", json=_body())
    r2 = await client.post("/api/providers", json=_body())
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_post_conflict_builtin_409(client):
    """seed 后内置已在 DB;POST 同 id 触发已存在冲突。"""
    from drama_agent.provider.seed import seed_providers
    await seed_providers()
    r = await client.post("/api/providers", json=_body(provider_id="drama"))
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_builtin_is_editable_via_put(client):
    """内置可改凭证/模型(与自定义一视同仁)。"""
    from drama_agent.provider.seed import seed_providers
    await seed_providers()
    r = await client.put("/api/providers/drama", json=_body(
        provider_id="drama", label="DeepSeek", kind="llm", protocol="openai-compat",
        base_url="https://deepseek/v1", api_key="sk-new-key-9999",
        models=[{"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "kind": "llm"}],
    ))
    assert r.status_code == 200
    got = (await client.get("/api/providers/drama")).json()
    assert got["api_key"] == "sk-new-key-9999"


@pytest.mark.asyncio
async def test_builtin_cannot_be_deleted(client):
    from drama_agent.provider.seed import seed_providers
    await seed_providers()
    r = await client.delete("/api/providers/drama")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_delete_missing_404(client):
    assert (await client.put("/api/providers/nope", json=_body(provider_id="nope"))).status_code == 404
    assert (await client.delete("/api/providers/nope")).status_code == 404


@pytest.mark.asyncio
async def test_delete_then_gone(client):
    await client.post("/api/providers", json=_body())
    assert (await client.delete("/api/providers/mycorp")).status_code == 200
    assert (await client.get("/api/providers/mycorp")).status_code == 404


@pytest.mark.asyncio
async def test_validation_bad_protocol_422(client):
    r = await client.post("/api/providers", json=_body(protocol="no-such-proto"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_validation_model_kind_mismatch_422(client):
    r = await client.post("/api/providers", json=_body(
        kind="llm", models=[{"id": "v", "label": "V", "kind": "video"}]))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_validation_slash_in_id_422(client):
    r = await client.post("/api/providers", json=_body(provider_id="a/b"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_protocols_endpoint(client):
    r = await client.get("/api/providers/protocols")
    body = r.json()
    assert "openai-compat" in body["llm"]
    assert "seedance" in body["video"]


@pytest.mark.asyncio
async def test_created_model_appears_in_config_models(client):
    """写后 rebuild → 新自定义模型出现在建集下拉(/config/models)。"""
    await client.post("/api/providers", json=_body())
    models = (await client.get("/api/config/models")).json()["models"]
    assert any(m["value"] == "qwen-max" for m in models)


@pytest.mark.asyncio
async def test_protocols_includes_image(client):
    body = (await client.get("/api/providers/protocols")).json()
    assert "doubao-image" in body["image"] and "openai-image" in body["image"]


@pytest.mark.asyncio
async def test_create_image_provider_and_toggle_enabled(client):
    r = await client.post("/api/providers", json=_body(
        provider_id="myimg", kind="image", protocol="doubao-image",
        models=[{"id": "sd", "label": "SD", "kind": "image"}]))
    assert r.status_code == 200
    got = (await client.get("/api/providers/myimg")).json()
    assert got["kind"] == "image" and got["enabled"] is True
    r2 = await client.put("/api/providers/myimg", json=_body(
        provider_id="myimg", kind="image", protocol="doubao-image", enabled=False,
        models=[{"id": "sd", "label": "SD", "kind": "image"}]))
    assert r2.status_code == 200
    assert (await client.get("/api/providers/myimg")).json()["enabled"] is False


@pytest.mark.asyncio
async def test_create_provider_persists_is_default(client):
    body = {
        "provider_id": "acme", "label": "Acme", "kind": "llm", "protocol": "openai-compat",
        "base_url": "https://acme/v1", "api_key": "sk-x", "enabled": True,
        "models": [{"id": "m1", "label": "M1", "kind": "llm", "is_default": True}],
    }
    r = await client.post("/api/providers", json=body)
    assert r.status_code == 200
    got = await client.get("/api/providers/acme")
    assert got.json()["models"][0]["is_default"] is True


@pytest.mark.asyncio
async def test_setting_default_clears_other_providers_same_kind(client):
    """全局单默认:保存 B 的 llm 默认后,A 之前的 llm 默认被清;跨 kind 不受影响。"""
    await client.post("/api/providers", json={
        "provider_id": "pa", "label": "PA", "kind": "llm", "protocol": "openai-compat",
        "base_url": "https://a/v1", "api_key": "k", "enabled": True,
        "models": [{"id": "m1", "label": "M1", "kind": "llm", "is_default": True}],
    })
    await client.post("/api/providers", json={
        "provider_id": "vid", "label": "Vid", "kind": "video", "protocol": "seedance",
        "base_url": "https://v/v1", "api_key": "k", "enabled": True,
        "models": [{"id": "vd", "label": "VD", "kind": "video", "is_default": True}],
    })
    # B 设 llm 默认 → 清掉 A 的,但不动 video 的
    await client.post("/api/providers", json={
        "provider_id": "pb", "label": "PB", "kind": "llm", "protocol": "openai-compat",
        "base_url": "https://b/v1", "api_key": "k", "enabled": True,
        "models": [{"id": "m2", "label": "M2", "kind": "llm", "is_default": True}],
    })
    a = (await client.get("/api/providers/pa")).json()
    b = (await client.get("/api/providers/pb")).json()
    vid = (await client.get("/api/providers/vid")).json()
    assert a["models"][0]["is_default"] is False   # A 被清
    assert b["models"][0]["is_default"] is True     # B 保留
    assert vid["models"][0]["is_default"] is True   # 跨 kind 不受影响
