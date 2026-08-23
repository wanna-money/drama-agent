import base64
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from drama_agent.db.models import Base
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    orig_e, orig_f = db_session.engine, db_session.AsyncSessionLocal
    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_factory
    from drama_agent.db.session import get_db
    from drama_agent.main import app

    async def override_get_db():
        async with test_session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_generate_returns_base64_of_bytes(client):
    with patch("drama_agent.api.assets.asset_gen_service.generate_image",
               AsyncMock(return_value=[b"PNGBYTES"])):
        resp = await client.post("/api/assets/generate",
                                 json={"model_id": "doubao-seedream-3-0-t2i", "prompt": "a hero"})
    assert resp.status_code == 200
    imgs = resp.json()["images"]
    assert imgs == [base64.b64encode(b"PNGBYTES").decode()]


@pytest.mark.asyncio
async def test_generate_unknown_model_422(client):
    with patch("drama_agent.api.assets.asset_gen_service.generate_image",
               AsyncMock(side_effect=ValueError("Unknown model"))):
        resp = await client.post("/api/assets/generate", json={"model_id": "nope", "prompt": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_edit_missing_asset_404(client):
    with patch("drama_agent.api.assets.asset_gen_service.edit_image",
               AsyncMock(side_effect=LookupError("gone"))):
        resp = await client.post("/api/assets/edit",
                                 json={"asset_id": "gone", "model_id": "gpt-image-2",
                                       "prompt": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_unsupported_provider_501(client):
    with patch("drama_agent.api.assets.asset_gen_service.edit_image",
               AsyncMock(side_effect=NotImplementedError("Seedream 不支持编辑"))):
        resp = await client.post("/api/assets/edit",
                                 json={"asset_id": "a1", "model_id": "doubao-seedream-3-0-t2i",
                                       "prompt": "x"})
    assert resp.status_code == 501


@pytest.mark.asyncio
async def test_from_generated_persists_and_listable(client):
    b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    resp = await client.post("/api/assets/from-generated",
                             json={"category": "character", "name": "生成侠客", "image_b64": b64})
    assert resp.status_code == 200
    created = resp.json()
    assert created["name"] == "生成侠客"
    assert created["category"] == "character"
    listed = (await client.get("/api/assets")).json()
    assert any(a["id"] == created["id"] for a in listed)


@pytest.mark.asyncio
async def test_from_generated_bad_base64_422(client):
    resp = await client.post("/api/assets/from-generated",
                             json={"category": "character", "name": "x",
                                   "image_b64": "@@@not-base64@@@"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_from_generated_bad_category_422(client):
    b64 = base64.b64encode(b"x").decode()
    resp = await client.post("/api/assets/from-generated",
                             json={"category": "nope", "name": "x", "image_b64": b64})
    assert resp.status_code == 422
