"""Tests for VideoService providers."""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from drama_agent.services.video_service import VideoService, VideoTaskResult


def test_get_seedance_provider():
    svc = VideoService()
    from drama_agent.services.video_service import SeedanceVideoService
    provider = svc.get_provider("seedance")
    assert isinstance(provider, SeedanceVideoService)


def test_get_bailian_provider():
    svc = VideoService()
    from drama_agent.services.video_service import BailianVideoService
    provider = svc.get_provider("bailian")
    assert isinstance(provider, BailianVideoService)


def test_unknown_provider_raises():
    svc = VideoService()
    with pytest.raises(ValueError, match="Unknown video provider"):
        svc.get_provider("unknown_provider")


@pytest.mark.asyncio
async def test_bailian_create_task():
    """BailianVideoService.create_task sends correct request and returns task_id."""
    from drama_agent.services.video_service import BailianVideoService
    svc = BailianVideoService()

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"output": {"task_id": "bailian-task-123"}})

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_ctx

        task_id = await svc.create_task(prompt="A hero walks", duration=5)

    assert task_id == "bailian-task-123"
    mock_ctx.post.assert_awaited_once()
    call_kwargs = mock_ctx.post.call_args
    body = call_kwargs.kwargs["json"]
    assert body["input"]["prompt"] == "A hero walks"
    assert body["parameters"]["duration"] == 5


@pytest.mark.asyncio
async def test_bailian_get_task_succeeded():
    """BailianVideoService.get_task maps SUCCEEDED status correctly."""
    from drama_agent.services.video_service import BailianVideoService
    svc = BailianVideoService()

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "output": {
            "task_status": "SUCCEEDED",
            "video_url": "https://cdn.example.com/video.mp4",
        }
    })

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_ctx

        result = await svc.get_task("task-456")

    assert result.status == "succeeded"
    assert result.video_url == "https://cdn.example.com/video.mp4"
    assert result.last_frame_url is None


@pytest.mark.asyncio
async def test_bailian_get_task_failed():
    """BailianVideoService.get_task maps FAILED status correctly."""
    from drama_agent.services.video_service import BailianVideoService
    svc = BailianVideoService()

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={
        "output": {
            "task_status": "FAILED",
            "message": "Content policy violation",
        }
    })

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_ctx

        result = await svc.get_task("task-789")

    assert result.status == "failed"
    assert result.error == "Content policy violation"


@pytest.mark.asyncio
async def test_bailian_wait_for_task_polls_until_done():
    """wait_for_task polls until status is terminal."""
    from drama_agent.services.video_service import BailianVideoService
    svc = BailianVideoService()

    call_count = 0

    async def mock_get_task(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return VideoTaskResult(task_id, "running")
        return VideoTaskResult(task_id, "succeeded", video_url="http://video.mp4")

    with patch.object(svc, "get_task", side_effect=mock_get_task), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result = await svc.wait_for_task("task-poll", poll_interval=1, max_wait=60)

    assert result.status == "succeeded"
    assert call_count == 3


@pytest.mark.asyncio
async def test_bailian_wait_for_task_timeout():
    """wait_for_task raises TimeoutError if max_wait exceeded."""
    from drama_agent.services.video_service import BailianVideoService
    svc = BailianVideoService()

    async def always_running(task_id):
        return VideoTaskResult(task_id, "running")

    with patch.object(svc, "get_task", side_effect=always_running), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(TimeoutError):
            await svc.wait_for_task("task-timeout", poll_interval=5, max_wait=10)


def test_video_task_result_attributes():
    """VideoTaskResult stores all attributes correctly."""
    r = VideoTaskResult(
        task_id="t1",
        status="succeeded",
        video_url="http://video.mp4",
        last_frame_url="http://frame.jpg",
        error=None,
    )
    assert r.task_id == "t1"
    assert r.status == "succeeded"
    assert r.video_url == "http://video.mp4"
    assert r.last_frame_url == "http://frame.jpg"
    assert r.error is None
