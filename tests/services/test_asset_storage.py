"""素材库存储工厂 + 服务:测本地存储读写删、工厂选择、CFS stub、service CRUD。"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

_PNG = b"\x89PNG\r\n\x1a\n\x00fake"


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """内存库 + 临时素材目录(local backend)。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "asset_storage_backend", "local")
    monkeypatch.setattr(settings, "asset_local_dir", str(tmp_path / "assets"))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = factory
    yield factory
    db_session.AsyncSessionLocal = orig
    await engine.dispose()


# ── 存储工厂 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_local_storage_save_read_delete(tmp_path, monkeypatch):
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "asset_local_dir", str(tmp_path / "a"))
    from drama_agent.services.asset_storage import LocalAssetStorage
    st = LocalAssetStorage()
    key = await st.save(_PNG, "x.png")
    assert key.endswith(".png")
    assert await st.read(key) == _PNG
    assert st.url_for(key) == f"/api/assets/file/{key}"
    await st.delete(key)
    with pytest.raises(FileNotFoundError):
        await st.read(key)


def test_get_asset_storage_selects_backend(monkeypatch):
    from drama_agent.config import settings
    import drama_agent.services.asset_storage as m
    monkeypatch.setattr(settings, "asset_storage_backend", "local")
    assert isinstance(m.get_asset_storage(), m.LocalAssetStorage)
    monkeypatch.setattr(settings, "asset_storage_backend", "cfs")
    assert isinstance(m.get_asset_storage(), m.CfsAssetStorage)
    monkeypatch.setattr(settings, "asset_storage_backend", "unknown")
    assert isinstance(m.get_asset_storage(), m.LocalAssetStorage)  # 未知 → 默认 local


@pytest.mark.asyncio
async def test_cfs_backend_is_stub():
    from drama_agent.services.asset_storage import CfsAssetStorage
    st = CfsAssetStorage()
    with pytest.raises(NotImplementedError):
        await st.save(_PNG, "x.png")


# ── 服务 CRUD ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_asset_service_create_list_filter(db):
    from drama_agent.services import asset_service
    await asset_service.create_asset("character", "英雄", "主角", _PNG, "h.png", "image/png")
    await asset_service.create_asset("background", "城堡", None, _PNG, "c.png", "image/png")
    allrows = await asset_service.list_assets()
    assert len(allrows) == 2
    chars = await asset_service.list_assets("character")
    assert [r.name for r in chars] == ["英雄"]


@pytest.mark.asyncio
async def test_asset_service_update_replaces_file(db):
    from drama_agent.services import asset_service
    row = await asset_service.create_asset("prop", "剑", None, _PNG, "s.png", "image/png")
    old_key = row.storage_key
    updated = await asset_service.update_asset(
        row.id, name="宝剑", content=b"\x89PNGnew", filename="s2.png", mime="image/png")
    assert updated.name == "宝剑"
    assert updated.storage_key != old_key                 # 换图 → 新 key
    assert await asset_service.read_asset_bytes(row.id) == b"\x89PNGnew"


@pytest.mark.asyncio
async def test_asset_service_delete(db):
    from drama_agent.services import asset_service
    row = await asset_service.create_asset("costume", "战袍", None, _PNG, "r.png", "image/png")
    assert await asset_service.delete_asset(row.id) is True
    assert await asset_service.get_asset(row.id) is None
    assert await asset_service.delete_asset("nope") is False
