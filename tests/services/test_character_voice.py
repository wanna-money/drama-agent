import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db.models import Base, Character
from drama_agent.services import character_entity_service as svc


@pytest.fixture
async def mem_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    from drama_agent.db import session as db_session
    monkeypatch.setattr(db_session, "AsyncSessionLocal", maker)
    async with maker() as s:
        s.add(Character(id="c1", project_id="p1", name="林夏"))
        await s.commit()
    return maker


@pytest.mark.asyncio
async def test_set_then_read_voice_roundtrip(mem_session):
    fake_store = AsyncMock()
    fake_store.save.return_value = "abc.wav"
    fake_store.read.return_value = b"WAVDATA"
    with patch.object(svc, "get_asset_storage", return_value=fake_store):
        row = await svc.set_voice("c1", b"WAVDATA", "sample.wav", "audio/wav")
        assert row is not None and row.voice_key == "abc.wav"
        data = await svc.read_voice_bytes("c1")
    assert data == b"WAVDATA"
    fake_store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_voice_deletes_old_file(mem_session):
    fake_store = AsyncMock()
    fake_store.save.side_effect = ["old.wav", "new.mp3"]
    with patch.object(svc, "get_asset_storage", return_value=fake_store):
        await svc.set_voice("c1", b"A", "a.wav", "audio/wav")
        await svc.set_voice("c1", b"B", "b.mp3", "audio/mpeg")
    fake_store.delete.assert_awaited_once_with("old.wav")


@pytest.mark.asyncio
async def test_clear_voice_nulls_and_is_idempotent(mem_session):
    fake_store = AsyncMock()
    fake_store.save.return_value = "abc.wav"
    with patch.object(svc, "get_asset_storage", return_value=fake_store):
        await svc.set_voice("c1", b"A", "a.wav", "audio/wav")
        row = await svc.clear_voice("c1")
        assert row is not None and row.voice_key is None
        fake_store.delete.assert_awaited_with("abc.wav")
        again = await svc.clear_voice("c1")
        assert again is not None and again.voice_key is None


@pytest.mark.asyncio
async def test_voice_ops_on_missing_character_return_none(mem_session):
    fake_store = AsyncMock()
    fake_store.save.return_value = "x.wav"
    with patch.object(svc, "get_asset_storage", return_value=fake_store):
        assert await svc.set_voice("nope", b"A", "a.wav", "audio/wav") is None
        assert await svc.read_voice_bytes("nope") is None
        assert await svc.clear_voice("nope") is None
