"""Tests for video_generator and video_assembler nodes."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
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
        "episode_id": "ep-proj-vid",
        "title": "T", "raw_input": "s", "genre": "action",
        "story_analysis": None, "screenplay": "", "screenplay_approved": True,
        "screenplay_revision_notes": "", "shots": shots, "prompts": prompts,
        "prompts_approved": True, "prompt_revision_notes": "", "videos": [],
        "references": [], "current_stage": "prompts_approved",
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

    # Second call chains last_frame_url as a first_frame reference (Phase A: references interface)
    refs = captured_calls[1].get("references") or []
    assert any(r.kind == "first_frame" and r.url == "http://last_frame.jpg" for r in refs)


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


@pytest.mark.asyncio
async def test_video_generator_uses_edited_negative_prompt(tmp_path):
    """video_generator uses edited_negative_prompt when available (not the original negative_prompt)."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [{**state["prompts"][0], "edited_negative_prompt": "no watermark, no blur"}]

    captured = {}
    async def mock_create(**kwargs):
        captured["negative_prompt"] = kwargs.get("negative_prompt")
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

    assert captured["negative_prompt"] == "no watermark, no blur"


@pytest.mark.asyncio
async def test_video_generator_empty_edited_negative_prompt_is_not_ignored(tmp_path):
    """用户故意把负向 prompt 清空为 '' 时,必须真正传空字符串,不能因为 falsy 被 `or` 退回原值。"""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    # 原始 negative_prompt 是 "bad"(见 make_state_with_prompts fixture);用户编辑为空字符串。
    state["prompts"] = [{**state["prompts"][0], "edited_negative_prompt": ""}]

    captured = {}
    async def mock_create(**kwargs):
        captured["negative_prompt"] = kwargs.get("negative_prompt")
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

    assert captured["negative_prompt"] == ""


@pytest.mark.asyncio
async def test_video_generator_falls_back_to_negative_prompt_when_not_edited(tmp_path):
    """未编辑(edited_negative_prompt 不存在)时,仍应使用原始 negative_prompt——不回归既有行为。"""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    # make_state_with_prompts 的 fixture 本就不带 edited_negative_prompt 键,直接用其原始 prompts[0]。

    captured = {}
    async def mock_create(**kwargs):
        captured["negative_prompt"] = kwargs.get("negative_prompt")
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

    assert captured["negative_prompt"] == "bad"


@pytest.mark.asyncio
async def test_video_generator_explicit_none_edited_negative_prompt_falls_back(tmp_path):
    """key 存在但值为 None(prompt_engineer 的实际产出形态)时,必须回落到原始 negative_prompt。

    这是本 Task 与 Task 6 `graph.py` 合并逻辑的关键差异:`prompt_engineer` 建 prompt 时
    就把 `edited_negative_prompt` 显式置为 None,所以"未编辑"在生产中表现为 key 在、值为 None。
    若这里照抄 Task 6 的 dict-membership(`"edited_negative_prompt" in prompt`)写法,
    未编辑的镜头会把 None 当成编辑值送给 provider —— 这条测试专门拦这个。
    """
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [{**state["prompts"][0], "edited_negative_prompt": None}]

    captured = {}
    async def mock_create(**kwargs):
        captured["negative_prompt"] = kwargs.get("negative_prompt")
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

    assert captured["negative_prompt"] == "bad"


@pytest.mark.asyncio
async def test_video_generator_minimax_branch_uses_state_resolution(tmp_path):
    """minimax provider gets resolution from state (default 768P) and reference_role."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [{**state["shots"][0], "duration_seconds": 7}]
    state["prompts"] = [state["prompts"][0]]
    state["video_provider"] = "minimax"
    state["resolution"] = "2K"

    captured = {}
    async def mock_create(**kwargs):
        captured.update(kwargs)
        return "mm-task"

    mock_provider = AsyncMock()
    mock_provider.create_task = mock_create
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("mm-task", "succeeded", video_url="http://v.mp4", last_frame_url=None))

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock):

        result = await video_generator_node(state)

    assert captured["resolution"] == "2K"
    assert captured["duration"] == 7
    assert result["videos"][0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_video_generator_minimax_default_resolution(tmp_path):
    """minimax provider falls back to 768P when state has no resolution."""
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [state["prompts"][0]]
    state["video_provider"] = "minimax"
    # no "resolution" key

    captured = {}
    async def mock_create(**kwargs):
        captured.update(kwargs)
        return "mm-task"

    mock_provider = AsyncMock()
    mock_provider.create_task = mock_create
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("mm-task", "succeeded", video_url="http://v.mp4", last_frame_url=None))

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file",
               new_callable=AsyncMock):

        await video_generator_node(state)

    assert captured["resolution"] == "768P"


@pytest.mark.asyncio
async def test_video_generator_writes_root_artifact(tmp_path):
    from drama_agent.workflow.nodes.video_generator import video_generator_node

    state = make_state_with_prompts(tmp_path)
    state["shots"] = [state["shots"][0]]
    state["prompts"] = [state["prompts"][0]]
    state["video_provider"] = "minimax"
    state["resolution"] = "768P"

    mock_provider = AsyncMock()
    mock_provider.create_task = AsyncMock(return_value="mm-task")
    mock_provider.wait_for_task = AsyncMock(return_value=
        VideoTaskResult("mm-task", "succeeded", video_url="http://v.mp4", last_frame_url=None))

    created_roots = []

    async def fake_create_root(session, **kwargs):
        created_roots.append(kwargs)
        return {"id": "root-1", **kwargs}

    with patch("drama_agent.services.video_service.video_service.get_provider", return_value=mock_provider), \
         patch("drama_agent.services.storage_service.storage_service.get_project_output_dir", return_value=tmp_path), \
         patch("drama_agent.services.storage_service.storage_service.download_file", new_callable=AsyncMock), \
         patch("drama_agent.services.artifact_service.create_root", side_effect=fake_create_root), \
         patch("drama_agent.workflow.nodes.video_generator.AsyncSessionLocal") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        await video_generator_node(state)

    assert len(created_roots) == 1
    assert created_roots[0]["provider"] == "minimax"
    assert created_roots[0]["resolution"] == "768P"
    assert created_roots[0]["task_id"] == "mm-task"
    assert created_roots[0]["prompt_text"] == "city shot"  # prompts[0].prompt_text


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
        "episode_id": "ep-proj-asm",
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
        "episode_id": "ep-proj-empty",
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
        "episode_id": "ep-proj-ffmpeg-fail",
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
        "episode_id": "ep-proj-order",
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
    lines = [ln for ln in concat_content.strip().splitlines() if ln]
    # s1 should appear before s2
    assert lines[0].endswith("s1.mp4'")
    assert lines[1].endswith("s2.mp4'")
