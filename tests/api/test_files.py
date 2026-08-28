"""Tests for files API — upload, download, list, export."""
import pytest
import io
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    original_engine = db_session.engine
    original_factory = db_session.AsyncSessionLocal
    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    from drama_agent.main import app
    from drama_agent.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    db_session.engine = original_engine
    db_session.AsyncSessionLocal = original_factory
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.fixture
async def project_id(client):
    resp = await client.post("/api/projects", json={"title": "File Test", "genre": "drama"})
    return resp.json()["id"]


@pytest.fixture
async def episode_id(client, project_id):
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文"))
        await s.commit()
    resp = await client.post(f"/api/projects/{project_id}/episodes",
                             json={"title": "e", "script_id": sid})
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_upload_reference_image(client, project_id, tmp_path):
    """上传参考图(项目级,角色跨集共享)。"""
    fake_image = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100  # fake PNG bytes
    with patch("drama_agent.services.storage_service.storage_service.save_project_image",
               new_callable=AsyncMock, return_value=("test.png", str(tmp_path / "test.png"))):
        resp = await client.post(
            f"/api/projects/{project_id}/files/upload",
            files={"file": ("test.png", io.BytesIO(fake_image), "image/png")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "path" in data
    assert data["filename"] == "test.png"


@pytest.mark.asyncio
async def test_upload_to_nonexistent_project(client):
    """Uploading to a nonexistent project returns 404."""
    with patch("drama_agent.services.storage_service.storage_service.save_project_image",
               new_callable=AsyncMock):
        resp = await client.post(
            "/api/projects/no-such-project/files/upload",
            files={"file": ("img.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_file_not_found(client, episode_id, tmp_path):
    """Downloading a nonexistent file returns 404(集级)。用真实空目录 + 不存在文件名。"""
    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/episodes/{episode_id}/files/nonexistent.mp4")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_videos_empty(client, episode_id, tmp_path):
    """Listing videos returns empty list when no videos exist."""
    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/episodes/{episode_id}/videos")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_videos_with_clips(client, episode_id, tmp_path):
    """Listing videos returns shot clips but excludes final.mp4."""
    (tmp_path / "shot1.mp4").write_bytes(b"fake video 1")
    (tmp_path / "shot2.mp4").write_bytes(b"fake video 2")
    (tmp_path / "final.mp4").write_bytes(b"final")

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/episodes/{episode_id}/videos")
    assert resp.status_code == 200
    videos = resp.json()
    filenames = [v["filename"] for v in videos]
    assert "shot1.mp4" in filenames
    assert "shot2.mp4" in filenames
    assert "final.mp4" not in filenames  # excluded


@pytest.mark.asyncio
async def test_export_final_video_not_found(client, episode_id, tmp_path):
    """Export returns 404 when final video not assembled yet."""
    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/episodes/{episode_id}/export")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_final_video_exists(client, episode_id, tmp_path):
    """Export returns the final video file when it exists."""
    final = tmp_path / "final.mp4"
    final.write_bytes(b"fake final video content")

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/episodes/{episode_id}/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("video/mp4")
    assert resp.content == b"fake final video content"


# ── 参考图绑定:ref_type 的权威在后端 ────────────────────────────────
@pytest.mark.asyncio
async def test_put_then_get_references_round_trips_ref_type(client, episode_id):
    """从素材库选的角色参考图,名字不在 story_analysis 里也必须仍归为 character。

    这是回归拦截:ref_type 若只存在于请求体、既不落库也不下发,前端只能按
    "名字在不在角色表里"反猜类型,于是这条被判成了背景图。
    """
    put = await client.put(f"/api/episodes/{episode_id}/references", json={
        "references": [{"key": "测试", "ref_type": "character", "image_url": "/img/t.png"}],
    })
    assert put.status_code == 200

    got = await client.get(f"/api/episodes/{episode_id}/references")
    assert got.status_code == 200
    entries = {e["key"]: e for e in got.json()["references"]}
    assert entries["测试"]["ref_type"] == "character"
    assert entries["测试"]["image_url"] == "/img/t.png"


@pytest.mark.asyncio
async def test_put_references_rejects_unknown_ref_type(client, episode_id):
    """非法 ref_type → 400,不能静默落成自由字符串。"""
    resp = await client.put(f"/api/episodes/{episode_id}/references", json={
        "references": [{"key": "道具", "ref_type": "prop", "image_url": "/img/p.png"}],
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_references_replaces_whole_list(client, episode_id):
    """PUT 是整表替换:上一次提交里被删掉的条目不该复活。"""
    await client.put(f"/api/episodes/{episode_id}/references", json={
        "references": [
            {"key": "A", "ref_type": "character", "image_url": "/a.png"},
            {"key": "B", "ref_type": "background", "image_url": "/b.png"},
        ],
    })
    await client.put(f"/api/episodes/{episode_id}/references", json={
        "references": [{"key": "A", "ref_type": "character", "image_url": "/a.png"}],
    })
    keys = [e["key"] for e in (await client.get(f"/api/episodes/{episode_id}/references")).json()["references"]]
    assert keys == ["A"]


@pytest.mark.asyncio
async def test_get_references_does_not_list_character_placeholders(client, project_id):
    """角色**不再**产生参考图占位 —— 角色形象的唯一配置处是「角色」页的造型。

    从源剧本的 story_analysis 列角色占位,会与造型指派重复表达同一件事。
    这条删掉就会放走那个双入口回归。
    """
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Script
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="剧", source_text="x", content="正文",
                     story_analysis={"characters": [{"name": "陈薇"}, {"name": "林夏"}]}))
        await s.commit()
    eid = (await client.post(f"/api/projects/{project_id}/episodes",
                             json={"title": "e", "script_id": sid})).json()["id"]

    entries = (await client.get(f"/api/episodes/{eid}/references")).json()["references"]
    assert [e["key"] for e in entries] == []


@pytest.mark.asyncio
async def test_get_references_lists_background_placeholders_from_shots(client, episode_id):
    """分镜地点仍要自动列成待上传的背景占位 —— 背景没有实体,这是它唯一的入口,
    去掉的话用户得自己把每个场景名敲一遍。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
        ep.state_snapshot = {"shots": [{"location": "INT. 客厅 - 日"}, {"location": "天台"}]}
        await s.commit()

    entries = (await client.get(f"/api/episodes/{episode_id}/references")).json()["references"]
    assert [(e["key"], e["ref_type"]) for e in entries] == [
        ("INT. 客厅 - 日", "background"),
        ("天台", "background"),
    ]
    # 仅探测出来的占位不是用户记录 → 不给删除入口(前端据此隐藏 ✕)
    assert all(e["removable"] is False for e in entries)


@pytest.mark.asyncio
async def test_get_references_upgrades_legacy_snapshot(client, episode_id):
    """旧库里的 character_references 快照要按角色读出来,不能整体错位到背景组。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from sqlalchemy import select
    async with db_session.AsyncSessionLocal() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == episode_id))).scalar_one()
        ep.state_snapshot = {"character_references": {"旧角色": "/legacy.png"}}
        await s.commit()

    entries = (await client.get(f"/api/episodes/{episode_id}/references")).json()["references"]
    assert [(e["key"], e["ref_type"], e["image_url"]) for e in entries] == [
        ("旧角色", "character", "/legacy.png"),
    ]


# ── 图片读取:可读类型 ⊃ 可上传类型 ──────────────────────────────────
@pytest.mark.asyncio
async def test_serve_keyframe_image_is_allowed(client, project_id, tmp_path):
    """关键帧由节点生成、不接受上传,但其 URL 必须可读 —— 否则关键帧缩略图必然坏掉。"""
    (tmp_path / "s1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch("drama_agent.services.storage_service.storage_service.get_project_image_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/projects/{project_id}/images/keyframe/s1.png")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_serve_image_rejects_unknown_type(client, project_id, tmp_path):
    with patch("drama_agent.services.storage_service.storage_service.get_project_image_dir",
               return_value=tmp_path):
        resp = await client.get(f"/api/projects/{project_id}/images/bogus/s1.png")
    assert resp.status_code == 400
