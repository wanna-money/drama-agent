import base64
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig_e, orig_f = db_session.engine, db_session.AsyncSessionLocal
    db_session.engine = eng
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    from drama_agent.main import app
    from drama_agent.db.session import get_db

    async def override():
        async with db_session.AsyncSessionLocal() as s:
            yield s
    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    db_session.engine, db_session.AsyncSessionLocal = orig_e, orig_f
    app.dependency_overrides.clear()
    await eng.dispose()


@pytest.mark.asyncio
async def test_character_and_look_crud(client):
    r = await client.post("/api/projects/p1/characters", json={"name": "林夏"})
    assert r.status_code == 200
    cid = r.json()["id"]
    assert any(c["id"] == cid for c in (await client.get("/api/projects/p1/characters")).json())
    r2 = await client.post(f"/api/projects/p1/characters/{cid}/looks", json={"name": "日常装"})
    assert r2.status_code == 200 and r2.json()["is_default"] is True  # 首个默认


@pytest.mark.asyncio
async def test_cross_project_character_access_404(client):
    """#3: 用别项目 pid 配上角色 cid → 404,不能跨项目改/删/读。"""
    cid = (await client.post("/api/projects/p1/characters", json={"name": "林夏"})).json()["id"]
    # 正确项目可改
    assert (await client.put(f"/api/projects/p1/characters/{cid}",
                             json={"name": "林夏2"})).status_code == 200
    # 错误项目(p2)一律 404
    assert (await client.put(f"/api/projects/p2/characters/{cid}",
                             json={"name": "hack"})).status_code == 404
    assert (await client.delete(f"/api/projects/p2/characters/{cid}")).status_code == 404
    assert (await client.get(f"/api/projects/p2/characters/{cid}/looks")).status_code == 404


@pytest.mark.asyncio
async def test_cross_character_look_access_404(client):
    """#3: 造型 lid 不属于 URL 里的角色 cid → 404。"""
    c1 = (await client.post("/api/projects/p1/characters", json={"name": "A"})).json()["id"]
    c2 = (await client.post("/api/projects/p1/characters", json={"name": "B"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{c1}/looks",
                             json={"name": "L"})).json()["id"]
    # lid 属于 c1,用 c2 访问 → 404
    assert (await client.put(f"/api/projects/p1/characters/{c2}/looks/{lid}",
                             json={"name": "hack"})).status_code == 404
    assert (await client.delete(f"/api/projects/p1/characters/{c2}/looks/{lid}")).status_code == 404


@pytest.mark.asyncio
async def test_views_from_generated_persists(client):
    r = await client.post("/api/projects/p1/characters", json={"name": "林夏"})
    cid = r.json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    b = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
    resp = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/views-from-generated",
        json={"front_b64": b, "side_b64": b, "back_b64": b})
    assert resp.status_code == 200
    assert resp.json()["front_key"]


@pytest.mark.asyncio
async def test_generate_sheet_unknown_model_422(client):
    r = await client.post("/api/projects/p1/characters", json={"name": "林夏"})
    cid = r.json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "d"})).json()["id"]
    with patch("drama_agent.api.characters.character_gen_service.generate_four_view_sheet",
               AsyncMock(side_effect=ValueError("unknown model"))):
        resp = await client.post(
            f"/api/projects/p1/characters/{cid}/looks/{lid}/generate-sheet",
            json={"model_id": "nope"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_sheet_returns_four_views(client):
    """四视图升级:生成接口须返回 front/side/back/face 四张。"""
    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    with patch("drama_agent.api.characters.character_gen_service.generate_four_view_sheet",
               AsyncMock(return_value=(b"sheet", (b"f", b"s", b"b", b"c")))):
        resp = await client.post(
            f"/api/projects/p1/characters/{cid}/looks/{lid}/generate-sheet",
            json={"model_id": "seedream"})
    assert resp.status_code == 200
    v = resp.json()["views"]
    assert set(v.keys()) == {"front", "side", "back", "face"}
    assert v["face"] == base64.b64encode(b"c").decode()


@pytest.mark.asyncio
async def test_generate_sheet_returns_sheet_for_manual_crop_when_auto_crop_fails(client):
    """自动裁切失败时生成本身仍算成功:回 200 + views=None + 原图,供前端转人工裁切。
    若这里改回抛错,用户就得为一次切不开的图重新烧一次文生图 —— 这条拦的是那个回归。"""
    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    with patch("drama_agent.api.characters.character_gen_service.generate_four_view_sheet",
               AsyncMock(return_value=(b"sheet", None))):
        resp = await client.post(
            f"/api/projects/p1/characters/{cid}/looks/{lid}/generate-sheet",
            json={"model_id": "seedream"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["views"] is None
    assert body["sheet_b64"] == base64.b64encode(b"sheet").decode()


@pytest.mark.asyncio
async def test_views_from_generated_stores_face(client):
    """face_b64 须被落盘并回显 face_key。"""
    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    b = base64.b64encode(b"x").decode()
    resp = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/views-from-generated",
        json={"front_b64": b, "face_b64": b})
    assert resp.status_code == 200
    assert resp.json()["face_key"]


@pytest.mark.asyncio
async def test_import_from_asset_fills_views(client, monkeypatch):
    """从素材库导入:服务返回的 Look row 须被序列化回显(含 face_key)。"""
    import drama_agent.api.characters as chars

    class _Row:  # 模拟 Look ORM row(_look_dict 读这些属性)
        id = "lk"
        character_id = "cid"
        name = "默认"
        is_default = True
        front_key = "f"
        side_key = "s"
        back_key = "b"
        face_key = "c"

    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    monkeypatch.setattr(chars.character_import_service, "import_asset_as_look_views",
                        AsyncMock(return_value=_Row()))
    r = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/import-from-asset",
        json={"asset_id": "a-1"})
    assert r.status_code == 200
    assert r.json()["face_key"] == "c"


@pytest.mark.asyncio
async def test_import_from_asset_missing_asset_404(client, monkeypatch):
    """素材不存在(服务抛 ValueError)→ 404。"""
    import drama_agent.api.characters as chars

    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    monkeypatch.setattr(chars.character_import_service, "import_asset_as_look_views",
                        AsyncMock(side_effect=ValueError("素材不存在")))
    r = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/import-from-asset",
        json={"asset_id": "nope"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_import_from_asset_crop_failure_is_422_not_404(client, monkeypatch):
    """切不开是内容问题 → 422(前端据此引导人工裁切);与"素材不存在"的 404 必须分开。
    两者混成同一个码,前端就无从判断该弹裁切器还是提示数据缺失。"""
    import drama_agent.api.characters as chars
    from drama_agent.services.character_gen_service import CropFailed

    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    monkeypatch.setattr(chars.character_import_service, "import_asset_as_look_views",
                        AsyncMock(side_effect=CropFailed("未能自动识别四视图分界")))
    r = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/import-from-asset",
        json={"asset_id": "a-1"})
    assert r.status_code == 422
    assert "四视图分界" in r.json()["detail"]


@pytest.mark.asyncio
async def test_import_from_asset_unreadable_image_is_422_not_500(client, monkeypatch):
    """素材不是图片时 PIL 抛 UnidentifiedImageError —— 必须映射 422,不能裸 500。"""
    import drama_agent.api.characters as chars
    from PIL import UnidentifiedImageError

    cid = (await client.post("/api/projects/p1/characters",
                             json={"name": "林夏"})).json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "日常装"})).json()["id"]
    monkeypatch.setattr(chars.character_import_service, "import_asset_as_look_views",
                        AsyncMock(side_effect=UnidentifiedImageError("bad")))
    r = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/import-from-asset",
        json={"asset_id": "a-1"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_upload_bad_view_422(client):
    r = await client.post("/api/projects/p1/characters", json={"name": "林夏"})
    cid = r.json()["id"]
    lid = (await client.post(f"/api/projects/p1/characters/{cid}/looks",
                             json={"name": "d"})).json()["id"]
    resp = await client.post(
        f"/api/projects/p1/characters/{cid}/looks/{lid}/views/sideways",
        files={"file": ("f.png", b"x", "image/png")})
    assert resp.status_code == 422
