import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db.models import Base, Character
from drama_agent.main import app
from drama_agent.db import session as db_session


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(Character(id="c1", project_id="p1", name="林夏"))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await engine.dispose()


@pytest.mark.asyncio
async def test_upload_voice_ok_sets_voice_key(client):
    store = AsyncMock()
    store.save.return_value = "abc.wav"
    with patch("drama_agent.services.character_entity_service.get_asset_storage", return_value=store), \
         patch("mutagen.File") as mf:
        mf.return_value.info.length = 5.0
        r = await client.post("/api/projects/p1/characters/c1/voice",
                              files={"file": ("s.wav", b"WAV", "audio/wav")})
    assert r.status_code == 200 and r.json()["voice_key"] == "abc.wav"


@pytest.mark.asyncio
async def test_upload_voice_bad_duration_422(client):
    store = AsyncMock()
    with patch("drama_agent.services.character_entity_service.get_asset_storage", return_value=store), \
         patch("mutagen.File") as mf:
        mf.return_value.info.length = 30.0
        r = await client.post("/api/projects/p1/characters/c1/voice",
                              files={"file": ("s.wav", b"WAV", "audio/wav")})
    assert r.status_code == 422 and "2" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upload_voice_cross_project_404(client):
    r = await client.post("/api/projects/OTHER/characters/c1/voice",
                          files={"file": ("s.wav", b"WAV", "audio/wav")})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_serve_voice_infers_mime(client):
    store = AsyncMock()
    store.read.return_value = b"WAVDATA"
    with patch("drama_agent.api.characters.get_asset_storage", return_value=store):
        r = await client.get("/api/characters/voice/abc.mp3")
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/mpeg")


@pytest.mark.asyncio
async def test_delete_voice_clears(client):
    store = AsyncMock()
    store.save.return_value = "abc.wav"
    with patch("drama_agent.services.character_entity_service.get_asset_storage", return_value=store), \
         patch("mutagen.File") as mf:
        mf.return_value.info.length = 5.0
        await client.post("/api/projects/p1/characters/c1/voice",
                          files={"file": ("s.wav", b"WAV", "audio/wav")})
        r = await client.delete("/api/projects/p1/characters/c1/voice")
    assert r.status_code == 200 and r.json()["voice_key"] is None
