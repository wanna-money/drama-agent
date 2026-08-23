"""assets API:上传/列表/取文件/编辑/删除 + 分类过滤 + from-asset 拷贝进剧集参考。"""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client(tmp_path, monkeypatch):
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "asset_storage_backend", "local")
    monkeypatch.setattr(settings, "asset_local_dir", str(tmp_path / "assets"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
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
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await te.dispose()


_PNG = b"\x89PNG\r\n\x1a\n"


def _upload(category="character", name="英雄"):
    return {"files": {"file": ("h.png", _PNG, "image/png")},
            "data": {"category": category, "name": name}}


@pytest.mark.asyncio
async def test_create_list_serve_and_filter(client):
    r = await client.post("/api/assets", **_upload())
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "character" and body["name"] == "英雄"
    assert body["url"].startswith("/api/assets/file/")
    # 列表
    lst = (await client.get("/api/assets")).json()
    assert len(lst) == 1
    # 取文件
    f = await client.get(body["url"])
    assert f.status_code == 200 and f.content == _PNG
    # 分类过滤
    await client.post("/api/assets", **_upload(category="background", name="城堡"))
    chars = (await client.get("/api/assets?category=character")).json()
    assert {a["name"] for a in chars} == {"英雄"}


@pytest.mark.asyncio
async def test_bad_category_422(client):
    r = await client.post("/api/assets", files={"file": ("h.png", _PNG, "image/png")},
                          data={"category": "weapon", "name": "x"})  # weapon 非法(枚举无)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_and_delete(client):
    aid = (await client.post("/api/assets", **_upload())).json()["id"]
    r = await client.put(f"/api/assets/{aid}", data={"name": "改名"})
    assert r.status_code == 200 and r.json()["name"] == "改名"
    assert (await client.delete(f"/api/assets/{aid}")).status_code == 200
    assert (await client.delete(f"/api/assets/{aid}")).status_code == 404


@pytest.mark.asyncio
async def test_from_asset_copies_into_project(client):
    # 建项目 + 素材,拷贝进项目参考,返回与 upload 同形状 url
    proj = (await client.post("/api/projects", json={"title": "P", "genre": "drama"})).json()
    aid = (await client.post("/api/assets", **_upload(category="character", name="侠客"))).json()["id"]
    r = await client.post(f"/api/projects/{proj['id']}/files/from-asset",
                          json={"asset_id": aid, "type": "character"})
    assert r.status_code == 200
    out = r.json()
    assert out["type"] == "character"
    assert out["url"].startswith(f"/api/projects/{proj['id']}/images/character/")
    # 拷贝进的图能取到
    assert (await client.get(out["url"])).status_code == 200


@pytest.mark.asyncio
async def test_from_asset_missing_404(client):
    proj = (await client.post("/api/projects", json={"title": "P", "genre": "drama"})).json()
    r = await client.post(f"/api/projects/{proj['id']}/files/from-asset",
                          json={"asset_id": "nope", "type": "character"})
    assert r.status_code == 404
