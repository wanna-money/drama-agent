"""Tests for StorageService."""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import tempfile
import os


@pytest.fixture
def storage(tmp_path):
    """Create a StorageService with tmp dirs."""
    with patch.dict(os.environ, {
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "OUTPUT_DIR": str(tmp_path / "outputs"),
    }):
        from drama_agent.services.storage_service import StorageService
        svc = StorageService()
        svc.upload_dir = tmp_path / "uploads"
        svc.output_dir = tmp_path / "outputs"
        return svc


@pytest.mark.asyncio
async def test_save_upload_creates_file(storage, tmp_path):
    """save_upload writes file to upload dir and returns path."""
    content = b"fake image data"
    path = await storage.save_upload(content, "test.jpg")
    assert Path(path).exists()
    assert Path(path).read_bytes() == content
    assert path.endswith(".jpg")


@pytest.mark.asyncio
async def test_save_upload_unique_names(storage):
    """Each upload gets a unique filename."""
    path1 = await storage.save_upload(b"a", "photo.jpg")
    path2 = await storage.save_upload(b"b", "photo.jpg")
    assert path1 != path2


def test_get_project_output_dir_creates_dir(storage, tmp_path):
    """get_project_output_dir creates nested directory."""
    d = storage.get_project_output_dir("proj-abc-123")
    assert d.exists()
    assert d.is_dir()
    assert "proj-abc-123" in str(d)


def test_get_project_output_dir_idempotent(storage):
    """Calling get_project_output_dir twice is safe."""
    d1 = storage.get_project_output_dir("proj-x")
    d2 = storage.get_project_output_dir("proj-x")
    assert d1 == d2


@pytest.mark.asyncio
async def test_download_file_streams(storage, tmp_path):
    """download_file writes streamed content to dest path."""
    dest = tmp_path / "video.mp4"
    video_data = b"fake video bytes " * 1000

    class MockResp:
        def raise_for_status(self): pass
        async def aiter_bytes(self, chunk_size=None):
            yield video_data[:1000]
            yield video_data[1000:]

    class MockStreamCtx:
        async def __aenter__(self): return MockResp()
        async def __aexit__(self, *a): pass

    import httpx
    with patch.object(httpx.AsyncClient, "stream", return_value=MockStreamCtx()):
        result = await storage.download_file("http://example.com/video.mp4", dest)

    assert dest.exists()
    assert dest.read_bytes() == video_data
    assert result == str(dest)


@pytest.mark.asyncio
async def test_save_bytes(storage, tmp_path):
    """save_bytes writes arbitrary bytes to given path."""
    dest = tmp_path / "output" / "test.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = await storage.save_bytes(b"hello world", dest)
    assert dest.read_bytes() == b"hello world"
    assert result == str(dest)
