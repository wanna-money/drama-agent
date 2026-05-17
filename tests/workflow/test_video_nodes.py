"""Tests for video_generator and video_assembler nodes."""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock, call
from drama_agent.services.video_service import VideoTaskResult


def make_state_with_prompts(tmp_path):
    shots = [
        {"shot_id": "s1", "scene_number": 1, "shot_number": 1, "shot_type": "ELS",
         "camera_movement": "static", "duration_seconds": 5, "description": "city",
         "characters": [], "action": "", "dialogue": "", "location": "EXT."},
        {"shot_id": "s2", "scene_number": 1, "shot_number": 2, "shot_type": "MS",
         "camera_movement": "static", "duration_seconds": 5, "description": "hero",
         "characters": ["Hero"], "action": "", "dialogue": "", "location": "EXT."},
    ]
    prompts = [
        {"shot_id": "s1", "prompt_text": "city shot", "negative_prompt": "bad",
         "reference_image_url": None, "reference_role": None, "approved": True, "edited_prompt": None},
        {"shot_id": "s2", "prompt_text": "hero shot", "negative_prompt": "bad",
         "reference_image_url": None, "reference_role": "first_frame", "approved": True, "edited_prompt": None},
    ]
    return {
        "project_id": "proj-vid",
        "title": "T", "raw_input": "s", "genre": "action",
        "story_analysis": None, "screenplay": "", "screenplay_approved": True,
        "screenplay_revision_notes": "", "shots": shots, "prompts": prompts,
        "prompts_approved": True, "prompt_revision_notes": "", "videos": [],
        "character_references": {}, "current_stage": "prompts_approved",
        "error": None, "llm_model": "test", "video_model": "", "video_provider": "seedance",
        "assembled_video_path": None,
        "_tmp_path": tmp_path,
    }


@pytest.mark.asyncio
async def test_video_generator_succeeds(tmp_path):
    """video_generator_node generates videos for all prompts."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)

    mock_provider = AsyncMock()
    mock_provider.create_task = AsyncMock(side_effect=["task-1", "task-2"])
    mock_provider.wait_for_task = AsyncMock(side_effect=[
        VideoTaskResult("task-1", "succeeded", video_url="http://s1.mp4", last_frame_url="http://s1_last.jpg"),
        VideoTaskResult("task-2", "succeeded", video_url="http://s2.mp4", last_frame_url=None),
    ])

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock, return_value=str(tmp_path / "s1.mp4")):

        result = await video_generator_node(state)

    assert result["current_stage"] == "videos_generated"
    assert len(result["videos"]) == 2
    assert result["videos"][0]["status"] == "succeeded"
    assert result["videos"][1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_video_generator_chains_last_frame(tmp_path):
    """video_generator passes last_frame_url to next shot's create_task."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    captured_calls = []

    async def mock_create_task(**kwargs):
        captured_calls.append(kwargs)
        return f"task-{len(captured_calls)}"

    mock_provider = AsyncMock()
    mock_provider.create_task = mock_create_task
    mock_provider.wait_for_task = AsyncMock(side_effect=[
        VideoTaskResult("task-1", "succeeded", video_url="http://s1.mp4", last_frame_url="http://last_frame.jpg"),
        VideoTaskResult("task-2", "succeeded", video_url="http://s2.mp4", last_frame_url=None),
    ])

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock, return_value=str(tmp_path / "s.mp4")):

        await video_generator_node(state)

    # Second call should have reference_image=last_frame_url from first
    assert captured_calls[1].get("reference_image_url") == "http://last_frame.jpg"


@pytest.mark.asyncio
async def test_video_generator_skips_succeeded(tmp_path):
    """video_generator skips shots that already succeeded (resume support)."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["videos"] = [{
        "shot_id": "s1", "task_id": "existing-task", "status": "succeeded",
        "video_url": "http://existing.mp4", "last_frame_url": "http://lf.jpg",
        "local_path": str(tmp_path / "s1.mp4"), "error": None,
    }]

    mock_provider = AsyncMock()
    mock_provider.create_task = AsyncMock(return_value="task-new")
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("task-new", "succeeded", video_url="http://s2.mp4"))

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock, return_value=str(tmp_path / "s2.mp4")):

        result = await video_generator_node(state)

    # Only one new task created (s1 was skipped)
    assert mock_provider.create_task.call_count == 1
    assert len(result["videos"]) == 2


@pytest.mark.asyncio
async def test_video_generator_handles_failure(tmp_path):
    """video_generator marks shot as failed when provider fails."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [state["prompts"][0]]

    mock_provider = AsyncMock()
    mock_provider.create_task = AsyncMock(return_value="task-fail")
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("task-fail", "failed", error="API quota exceeded"))

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock):

        result = await video_generator_node(state)

    assert result["videos"][0]["status"] == "failed"
    assert result["videos"][0]["error"] == "API quota exceeded"


@pytest.mark.asyncio
async def test_video_generator_uses_edited_prompt(tmp_path):
    """video_generator uses edited_prompt when available."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [{**state["prompts"][0], "edited_prompt": "Custom edited prompt text"}]

    captured = {}
    async def mock_create(**kwargs):
        captured["prompt"] = kwargs.get("prompt")
        return "task-1"

    mock_provider = AsyncMock()
    mock_provider.create_task = mock_create
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("task-1", "succeeded", video_url="http://v.mp4"))

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock):

        await video_generator_node(state)

    assert captured["prompt"] == "Custom edited prompt text"


# ── video_assembler ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_video_assembler_creates_concat(tmp_path):
    """video_assembler runs ffmpeg concat and returns final path."""
    from drama_agent.workflow.nodes.video_assembler import video_assembler_node

    # Create fake video files
    (tmp_path / "s1.mp4").write_bytes(b"fake")
    (tmp_path / "s2.mp4").write_bytes(b"fake")

    state = {
        "project_id": "proj-asm",
        "shots": [
            {"shot_id": "s1", "scene_number": 1, "shot_number": 1},
            {"shot_id": "s2", "scene_number": 1, "shot_number": 2},
        ],
        "videos": [
            {"shot_id": "s1", "status": "succeeded", "local_path": str(tmp_path / "s1.mp4")},
            {"shot_id": "s2", "status": "succeeded", "local_path": str(tmp_path / "s2.mp4")},
        ],
    }

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):

        result = await video_assembler_node(state)

    assert result["current_stage"] == "completed"
    assert result["assembled_video_path"] == str(tmp_path / "final.mp4")


@pytest.mark.asyncio
async def test_video_assembler_no_videos():
    """video_assembler returns failure when no videos available."""
    from drama_agent.workflow.nodes.video_assembler import video_assembler_node

    state = {
        "project_id": "proj-empty",
        "shots": [{"shot_id": "s1", "scene_number": 1, "shot_number": 1}],
        "videos": [{"shot_id": "s1", "status": "failed", "local_path": None}],
    }

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=Path("/tmp/fake")):

        result = await video_assembler_node(state)

    assert result["current_stage"] == "assembly_failed"
    assert "error" in result


@pytest.mark.asyncio
async def test_video_assembler_ffmpeg_failure(tmp_path):
    """video_assembler reports error when ffmpeg exits non-zero."""
    from drama_agent.workflow.nodes.video_assembler import video_assembler_node

    (tmp_path / "s1.mp4").write_bytes(b"fake")
    state = {
        "project_id": "proj-ffmpeg-fail",
        "shots": [{"shot_id": "s1", "scene_number": 1, "shot_number": 1}],
        "videos": [{"shot_id": "s1", "status": "succeeded", "local_path": str(tmp_path / "s1.mp4")}],
    }

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"ffmpeg error: codec not found"))

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):

        result = await video_assembler_node(state)

    assert result["current_stage"] == "assembly_failed"
    assert "ffmpeg error" in result["error"]


@pytest.mark.asyncio
async def test_video_assembler_orders_by_shot(tmp_path):
    """video_assembler writes concat file in shot order, not video list order."""
    from drama_agent.workflow.nodes.video_assembler import video_assembler_node

    (tmp_path / "s1.mp4").write_bytes(b"s1")
    (tmp_path / "s2.mp4").write_bytes(b"s2")

    state = {
        "project_id": "proj-order",
        "shots": [
            {"shot_id": "s1", "scene_number": 1, "shot_number": 1},
            {"shot_id": "s2", "scene_number": 1, "shot_number": 2},
        ],
        # videos in reverse order
        "videos": [
            {"shot_id": "s2", "status": "succeeded", "local_path": str(tmp_path / "s2.mp4")},
            {"shot_id": "s1", "status": "succeeded", "local_path": str(tmp_path / "s1.mp4")},
        ],
    }

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("drama_agent.services.storage_service.storage_service.get_project_output_dir",
               return_value=tmp_path), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc):

        await video_assembler_node(state)

    concat_content = (tmp_path / "concat.txt").read_text()
    lines = [l for l in concat_content.strip().splitlines() if l]
    # s1 should appear before s2
    assert lines[0].endswith("s1.mp4'")
    assert lines[1].endswith("s2.mp4'")


# ── BailianVideoService status mapping ────────────────────────────────────────

@pytest.mark.asyncio
async def test_bailian_cancelled_maps_to_failed():
    """BailianVideoService.get_task should map CANCELLED to 'failed' not 'running'."""
    from drama_agent.services.video_service import BailianVideoService
    import httpx

    service = BailianVideoService()
    mock_response = {
        "output": {
            "task_status": "CANCELLED",
            "task_id": "t-123",
        }
    }
    with patch("httpx.AsyncClient") as MockClient:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value.get = AsyncMock(return_value=mock_resp)

        result = await service.get_task("t-123")

    assert result.status == "failed", f"Expected 'failed' but got '{result.status}'"


@pytest.mark.asyncio
async def test_bailian_unknown_status_maps_to_failed():
    """BailianVideoService.get_task should map UNKNOWN to 'failed'."""
    from drama_agent.services.video_service import BailianVideoService

    service = BailianVideoService()
    mock_response = {"output": {"task_status": "UNKNOWN"}}
    with patch("httpx.AsyncClient") as MockClient:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = MagicMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value.get = AsyncMock(return_value=mock_resp)

        result = await service.get_task("t-456")

    assert result.status == "failed"
