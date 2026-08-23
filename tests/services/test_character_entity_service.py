import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def db():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    yield
    db_session.AsyncSessionLocal = orig
    await eng.dispose()


@pytest.mark.asyncio
async def test_character_crud_roundtrip(db):
    from drama_agent.services import character_entity_service as s
    c = await s.create_character("p1", "林夏", "女主")
    assert c.id and c.name == "林夏"
    got = await s.list_characters("p1")
    assert [x.id for x in got] == [c.id]
    await s.update_character(c.id, name="林夏夏")
    assert (await s.get_character(c.id)).name == "林夏夏"
    assert await s.delete_character(c.id) is True
    assert await s.list_characters("p1") == []


@pytest.mark.asyncio
async def test_first_look_forced_default_and_uniqueness(db):
    from drama_agent.services import character_entity_service as s
    c = await s.create_character("p1", "林夏", None)
    l1 = await s.create_look(c.id, "日常装")
    assert l1.is_default is True   # 首个强制默认
    l2 = await s.create_look(c.id, "战斗装", is_default=True)
    # 设新默认应清旧默认
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as sess:
        rows = {x.id: x.is_default for x in (await sess.execute(select(Look))).scalars()}
    assert rows[l2.id] is True and rows[l1.id] is False


@pytest.mark.asyncio
async def test_set_view_writes_key_and_swaps(db, monkeypatch):
    from drama_agent.services import character_entity_service as s
    from drama_agent.db.enums import CharacterView
    saved = {}

    class FakeStorage:
        async def save(self, content, filename):
            key = f"k{len(saved)}"
            saved[key] = content
            return key

        async def delete(self, key):
            saved.pop(key, None)

    monkeypatch.setattr(s, "get_asset_storage", lambda: FakeStorage())
    c = await s.create_character("p1", "林夏", None)
    lk = await s.create_look(c.id, "日常装")
    r1 = await s.set_view(lk.id, CharacterView.FRONT.value, b"IMG1", "f.png", "image/png")
    assert r1.front_key == "k0"
    r2 = await s.set_view(lk.id, CharacterView.FRONT.value, b"IMG2", "f.png", "image/png")
    assert r2.front_key == "k1" and "k0" not in saved  # 换图删旧


@pytest.mark.asyncio
async def test_set_face_view_writes_face_key(db, monkeypatch):
    """face 视图须落在 face_key 列(_VIEW_KEY 未登记 face 时 KeyError)。"""
    from drama_agent.services import character_entity_service as s
    from drama_agent.db.enums import CharacterView

    class FakeStorage:
        async def save(self, content, filename):
            return "looks/xxx/face.png"

        async def delete(self, key):
            return None

    monkeypatch.setattr(s, "get_asset_storage", lambda: FakeStorage())
    c = await s.create_character("p1", "林夏", None)
    lk = await s.create_look(c.id, "默认", True)
    row = await s.set_view(lk.id, CharacterView.FACE.value, b"PNGBYTES", "face.png", "image/png")
    assert row.face_key == "looks/xxx/face.png"


@pytest.mark.asyncio
async def test_delete_look_cleans_face_file(db, monkeypatch):
    """删 look 须清理四视图文件,漏 face_key 会导致面部特写文件泄漏。"""
    from drama_agent.services import character_entity_service as s
    from drama_agent.db.enums import CharacterView
    saved: dict[str, bytes] = {}

    class FakeStorage:
        async def save(self, content, filename):
            key = f"k{len(saved)}"
            saved[key] = content
            return key

        async def delete(self, key):
            saved.pop(key, None)

    monkeypatch.setattr(s, "get_asset_storage", lambda: FakeStorage())
    c = await s.create_character("p1", "林夏", None)
    lk = await s.create_look(c.id, "日常装")
    for view in (CharacterView.FRONT, CharacterView.SIDE,
                 CharacterView.BACK, CharacterView.FACE):
        await s.set_view(lk.id, view.value, b"IMG", f"{view.value}.png", "image/png")
    assert len(saved) == 4
    assert await s.delete_look(lk.id) is True
    assert saved == {}   # 四个视图文件全部清掉,face 不残留


@pytest.mark.asyncio
async def test_delete_character_cascades_looks(db, monkeypatch):
    from drama_agent.services import character_entity_service as s
    monkeypatch.setattr(s, "get_asset_storage", lambda: type("S", (), {
        "delete": staticmethod(lambda k: None)})())
    c = await s.create_character("p1", "林夏", None)
    await s.create_look(c.id, "日常装")
    await s.delete_character(c.id)
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as sess:
        assert (await sess.execute(select(Look).where(Look.character_id == c.id))).first() is None
