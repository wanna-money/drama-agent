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
        s.add(Script(id=sid, title="剧", source_text="x", content="正文", status="completed"))
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
