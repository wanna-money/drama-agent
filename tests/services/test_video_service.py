"""Tests for VideoService providers."""
import pytest
from unittest.mock import AsyncMock, patch
from drama_agent.services.video_service import VideoService, VideoTaskResult


def test_get_seedance_provider():
    svc = VideoService()
    from drama_agent.services.video_service import SeedanceVideoService
    provider = svc.get_provider("seedance")
    assert isinstance(provider, SeedanceVideoService)


def test_unknown_provider_raises():
    svc = VideoService()
    with pytest.raises(ValueError, match="Unknown video provider"):
        svc.get_provider("unknown_provider")


# ---- MiniMax H3 provider ----

def test_get_minimax_provider():
    from drama_agent.services.video_service import MinimaxH3VideoService
    provider = VideoService().get_provider("minimax")
    assert isinstance(provider, MinimaxH3VideoService)


def test_minimax_build_content_text_only():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    content = svc._build_content("a hero walks")
    assert content == [{"type": "text", "text": "a hero walks"}]


def test_minimax_build_content_with_first_frame():
    from drama_agent.services.video_service import MinimaxH3VideoService
    from drama_agent.services.video_refs import RefImage
    svc = MinimaxH3VideoService()
    content = svc._build_content(
        "a hero walks",
        [RefImage(url="https://img/first.png", kind="first_frame")],
    )
    assert content[0] == {"type": "text", "text": "a hero walks"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "https://img/first.png"},
        "role": "first_frame",
    }


@pytest.mark.asyncio
async def test_minimax_create_task():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with patch.object(svc, "_request", new=AsyncMock(return_value={"task_id": "mm-123"})) as req:
        task_id = await svc.create_task(prompt="a hero walks", duration=6, resolution="768P")
    assert task_id == "mm-123"
    args, kwargs = req.call_args
    assert args[0] == "POST"
    assert args[1] == "/v2/video_generation"
    body = kwargs["json"]
    assert body["model"] == "MiniMax-H3"
    assert body["duration"] == 6
    assert body["resolution"] == "768P"
    assert body["content"][0] == {"type": "text", "text": "a hero walks"}


@pytest.mark.asyncio
async def test_minimax_get_task_succeeded_video():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    payload = {"task": {"id": "mm-1", "status": "succeeded",
                        "content": {"url": "https://cdn/out.mp4"}, "task_type": "generation"}}
    with patch.object(svc, "_request", new=AsyncMock(return_value=payload)):
        result = await svc.get_task("mm-1")
    assert result.status == "succeeded"
    assert result.video_url == "https://cdn/out.mp4"
    assert result.prompt is None


@pytest.mark.asyncio
async def test_minimax_get_task_context_ir_prompt():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    payload = {"task": {"id": "mm-2", "status": "succeeded",
                        "content": {"prompt": "enhanced!"}, "task_type": "h3_context_ir"}}
    with patch.object(svc, "_request", new=AsyncMock(return_value=payload)):
        result = await svc.get_task("mm-2")
    assert result.status == "succeeded"
    assert result.prompt == "enhanced!"
    assert result.video_url is None


@pytest.mark.asyncio
async def test_minimax_get_task_failed():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    payload = {"task": {"id": "mm-3", "status": "failed",
                        "error": {"code": "1026", "message": "sensitive content"}}}
    with patch.object(svc, "_request", new=AsyncMock(return_value=payload)):
        result = await svc.get_task("mm-3")
    assert result.status == "failed"
    assert "sensitive content" in result.error


@pytest.mark.asyncio
async def test_minimax_get_task_uses_path_param():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with patch.object(svc, "_request", new=AsyncMock(return_value={"task": {"status": "running"}})) as req:
        await svc.get_task("abc")
    args, _ = req.call_args
    assert args == ("GET", "/v2/query/video_generation/abc")


@pytest.mark.asyncio
async def test_minimax_wait_for_task_polls_until_done():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    calls = 0

    async def fake_get(task_id):
        nonlocal calls
        calls += 1
        if calls < 2:
            return VideoTaskResult(task_id, "running")
        return VideoTaskResult(task_id, "succeeded", video_url="https://cdn/out.mp4")

    with patch.object(svc, "get_task", side_effect=fake_get), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        result = await svc.wait_for_task("mm-1", poll_interval=1, max_wait=60)
    assert result.status == "succeeded"
    assert calls == 2


@pytest.mark.asyncio
async def test_minimax_list_tasks_flattens_filters():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    payload = {"items": [{"id": "1"}], "total": 1}
    with patch.object(svc, "_request", new=AsyncMock(return_value=payload)) as req:
        result = await svc.list_tasks(page_num=2, page_size=5, status="succeeded",
                                      task_ids=["a", "b"], task_type="generation")
    assert result["total"] == 1
    args, kwargs = req.call_args
    assert args == ("GET", "/v2/query/video_generation")
    params = kwargs["params"]
    assert params["page_num"] == 2
    assert params["page_size"] == 5
    assert params["filter.status"] == "succeeded"
    assert params["filter.task_ids"] == ["a", "b"]
    assert params["filter.task_type"] == "generation"


@pytest.mark.asyncio
async def test_minimax_delete_task():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    payload = {"task_id": "x", "action": "cancelled", "status": "cancelled"}
    with patch.object(svc, "_request", new=AsyncMock(return_value=payload)) as req:
        result = await svc.delete_task("x")
    assert result["action"] == "cancelled"
    args, _ = req.call_args
    assert args == ("DELETE", "/v2/video_generation/x")


@pytest.mark.asyncio
async def test_minimax_create_context_ir():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with patch.object(svc, "_request", new=AsyncMock(return_value={"task_id": "ir-1"})) as req:
        task_id = await svc.create_context_ir(prompt="scene", duration=5, ratio="16:9")
    assert task_id == "ir-1"
    args, kwargs = req.call_args
    assert args == ("POST", "/v2/h3_context_ir")
    assert kwargs["json"]["model"] == "MiniMax-H3"
    assert kwargs["json"]["content"][0]["text"] == "scene"


@pytest.mark.asyncio
async def test_minimax_regeneration_by_source_task_id():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with patch.object(svc, "_request", new=AsyncMock(return_value={"task_id": "re-1"})) as req:
        task_id = await svc.create_regeneration(source_task_id="src-1")
    assert task_id == "re-1"
    args, kwargs = req.call_args
    assert args == ("POST", "/v2/video_regeneration")
    body = kwargs["json"]
    assert body["source_task_id"] == "src-1"
    assert body["resolution"] == "2K"
    assert "content" not in body


@pytest.mark.asyncio
async def test_minimax_regeneration_by_base_video():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with patch.object(svc, "_request", new=AsyncMock(return_value={"task_id": "re-2"})) as req:
        task_id = await svc.create_regeneration(base_video_url="https://cdn/src.mp4")
    assert task_id == "re-2"
    body = req.call_args.kwargs["json"]
    assert body["content"][0] == {
        "type": "video_url",
        "video_url": {"url": "https://cdn/src.mp4"},
        "role": "base_video",
    }
    assert "source_task_id" not in body


@pytest.mark.asyncio
async def test_minimax_regeneration_requires_exactly_one_source():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService()
    with pytest.raises(ValueError):
        await svc.create_regeneration()
    with pytest.raises(ValueError):
        await svc.create_regeneration(source_task_id="a", base_video_url="b")


def test_provider_declarations():
    from drama_agent.services.video_service import (
        SeedanceVideoService, MinimaxH3VideoService,
    )
    assert SeedanceVideoService.provider_name == "seedance"
    assert "upscale" not in SeedanceVideoService.supported_actions
    assert MinimaxH3VideoService.provider_name == "minimax"
    assert set(MinimaxH3VideoService.supported_actions) == {"rerun", "regenerate", "upscale"}
