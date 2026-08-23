import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _state(provider="seedance"):
    return {
        "video_provider": provider, "resolution": None, "project_id": "p1", "episode_id": "e1",
        "video_model": "m", "videos": [],
        "shots": [{"shot_id": "s1", "duration_seconds": 5}],
        "prompts": [{"shot_id": "s1", "prompt_text": "hero", "negative_prompt": "",
                     "reference_image_url": None, "reference_role": None,
                     "edited_prompt": None}],
    }


@pytest.mark.asyncio
async def test_video_generator_calls_create_task_with_references():
    """统一走 references;首镜无连贯帧 → references 为空。"""
    import drama_agent.workflow.nodes.video_generator as vg
    fake = MagicMock()
    fake.create_task = AsyncMock(return_value="t1")
    fake.wait_for_task = AsyncMock(return_value=MagicMock(
        status="succeeded", video_url="http://v.mp4", last_frame_url="http://lf.png"))
    with patch.object(vg.video_service, "get_provider", return_value=fake), \
         patch.object(vg.storage_service, "get_project_output_dir", return_value=MagicMock()), \
         patch.object(vg.storage_service, "download_file", AsyncMock()), \
         patch.object(vg, "AsyncSessionLocal", MagicMock()):
        await vg.video_generator_node(_state())
    kw = fake.create_task.call_args.kwargs
    assert "references" in kw and kw["references"] == []   # 首镜无连贯
    assert kw["prompt"] == "hero"


@pytest.mark.asyncio
async def test_no_per_provider_branching_second_shot_chains_first_frame():
    """第二镜:上一镜末帧 → references 含一个 first_frame RefImage(连贯逻辑改由 references 表达)。"""
    import drama_agent.workflow.nodes.video_generator as vg
    st = _state()
    st["shots"].append({"shot_id": "s2", "duration_seconds": 5})
    st["prompts"].append({"shot_id": "s2", "prompt_text": "next", "negative_prompt": "",
                          "reference_image_url": None, "reference_role": None, "edited_prompt": None})
    fake = MagicMock()
    calls = []
    async def cap_create(**kw):
        calls.append(kw)
        return f"t{len(calls)}"
    fake.create_task = AsyncMock(side_effect=cap_create)
    fake.wait_for_task = AsyncMock(return_value=MagicMock(
        status="succeeded", video_url="http://v.mp4", last_frame_url="http://lf.png"))
    with patch.object(vg.video_service, "get_provider", return_value=fake), \
         patch.object(vg.storage_service, "get_project_output_dir", return_value=MagicMock()), \
         patch.object(vg.storage_service, "download_file", AsyncMock()), \
         patch.object(vg, "AsyncSessionLocal", MagicMock()):
        await vg.video_generator_node(st)
    # 第二次调用的 references 含一个 first_frame(上一镜末帧)
    refs2 = calls[1]["references"]
    assert len(refs2) == 1 and refs2[0].kind == "first_frame" and refs2[0].url == "http://lf.png"
