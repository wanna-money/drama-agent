from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db import session as db_session
from drama_agent.db.models import Base
from drama_agent.services import character_entity_service as ce


def _four_view_sheet() -> bytes:
    """白底 + 四块墨迹 + 三条内部空隙,供 crop_four_views 切四份。"""
    img = Image.new("RGB", (800, 100), (255, 255, 255))
    px = img.load()
    for x0, x1 in [(0, 150), (200, 350), (400, 550), (600, 750)]:
        for x in range(x0, x1):
            for y in range(30, 70):
                px[x, y] = (0, 0, 0)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeStorage:
    async def save(self, content, filename):
        return f"k/{filename}"

    async def delete(self, key):
        return None


@pytest.fixture
async def mem(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(db_session, "AsyncSessionLocal",
                        async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(ce, "get_asset_storage", lambda: _FakeStorage())
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_import_fills_four_views(mem, monkeypatch):
    from drama_agent.services import character_import_service as imp
    monkeypatch.setattr(imp.asset_service, "read_asset_bytes",
                        AsyncMock(return_value=_four_view_sheet()))
    ch = await ce.create_character("p1", "林夏", None)
    look = await ce.create_look(ch.id, "默认", True)
    row = await imp.import_asset_as_look_views(look.id, "asset-1")
    assert row is not None
    assert row.front_key and row.side_key and row.back_key and row.face_key


@pytest.mark.asyncio
async def test_import_missing_asset_raises(mem, monkeypatch):
    from drama_agent.services import character_import_service as imp
    monkeypatch.setattr(imp.asset_service, "read_asset_bytes", AsyncMock(return_value=None))
    ch = await ce.create_character("p1", "林夏", None)
    look = await ce.create_look(ch.id, "默认", True)
    with pytest.raises(ValueError):
        await imp.import_asset_as_look_views(look.id, "nope")


@pytest.mark.asyncio
async def test_import_missing_look_returns_none(mem, monkeypatch):
    """look 不存在 → None(调用方转 404),不抛。"""
    from drama_agent.services import character_import_service as imp
    monkeypatch.setattr(imp.asset_service, "read_asset_bytes",
                        AsyncMock(return_value=_four_view_sheet()))
    assert await imp.import_asset_as_look_views("no-such-look", "asset-1") is None
