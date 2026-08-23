import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_route_after_prompts_review_gates_on_use_keyframes():
    from drama_agent.workflow.graph import route_after_prompts_review
    assert route_after_prompts_review({"prompts_approved": False}) == "prompt_engineer"
    assert route_after_prompts_review(
        {"prompts_approved": True, "use_keyframes": True}) == "keyframe_generator"
    assert route_after_prompts_review(
        {"prompts_approved": True, "use_keyframes": False}) == "video_generator"
    # 缺省(无 use_keyframes)→ 直接 video_generator
    assert route_after_prompts_review({"prompts_approved": True}) == "video_generator"


def test_route_after_keyframes_review():
    from drama_agent.workflow.graph import route_after_keyframes_review
    assert route_after_keyframes_review({"keyframes_approved": True}) == "video_generator"
    assert route_after_keyframes_review({"keyframes_approved": False}) == "keyframe_generator"


@pytest.mark.asyncio
async def test_keyframes_review_approve_and_regenerate():
    from drama_agent.workflow.graph import keyframes_review_node
    st = {"prompts": [{"shot_id": "s1", "keyframe_url": "u1"},
                      {"shot_id": "s2", "keyframe_url": "u2"}],
          "shots": []}
    with patch("drama_agent.workflow.graph.interrupt", return_value={"approved": True}):
        out = await keyframes_review_node(st)
    assert out["keyframes_approved"] is True
    with patch("drama_agent.workflow.graph.interrupt",
               return_value={"approved": False, "regenerate_shot_ids": ["s1"]}):
        out = await keyframes_review_node(st)
    assert out["keyframes_approved"] is False
    kf = {p["shot_id"]: p["keyframe_url"] for p in out["prompts"]}
    assert kf["s1"] is None and kf["s2"] == "u2"   # 只清被打回的 s1


@pytest.mark.asyncio
async def test_keyframes_reject_empty_selection_regenerates_all():
    """#9: 打回但未勾选任何镜头 → 全部清空重生成(否则 keyframe_generator 全跳过→死循环)。"""
    from drama_agent.workflow.graph import keyframes_review_node
    st = {"prompts": [{"shot_id": "s1", "keyframe_url": "u1"},
                      {"shot_id": "s2", "keyframe_url": "u2"}],
          "shots": []}
    with patch("drama_agent.workflow.graph.interrupt",
               return_value={"approved": False, "regenerate_shot_ids": []}):
        out = await keyframes_review_node(st)
    assert out["keyframes_approved"] is False
    assert all(p["keyframe_url"] is None for p in out["prompts"])  # 全清 → 保证有进展


@pytest.mark.asyncio
async def test_video_generator_uses_keyframe_as_first_frame():
    import drama_agent.workflow.nodes.video_generator as vg
    st = {
        "video_provider": "seedance", "resolution": None, "project_id": "p1", "episode_id": "e1",
        "video_model": "m", "videos": [], "shots": [{"shot_id": "s1", "duration_seconds": 5}],
        "prompts": [{"shot_id": "s1", "prompt_text": "hero", "negative_prompt": "",
                     "reference_image_url": None, "reference_role": None, "edited_prompt": None,
                     "keyframe_url": "/api/projects/p1/images/keyframe/s1.png"}],
    }
    fake = MagicMock()
    fake.create_task = AsyncMock(return_value="t1")
    fake.wait_for_task = AsyncMock(return_value=MagicMock(
        status="succeeded", video_url="http://v.mp4", last_frame_url=None))
    with patch.object(vg.video_service, "get_provider", return_value=fake), \
         patch.object(vg.storage_service, "get_project_output_dir", return_value=MagicMock()), \
         patch.object(vg.storage_service, "download_file", AsyncMock()), \
         patch.object(vg, "AsyncSessionLocal", MagicMock()):
        await vg.video_generator_node(st)
    refs = fake.create_task.call_args.kwargs["references"]
    assert len(refs) == 1 and refs[0].kind == "first_frame"
    assert refs[0].url == "/api/projects/p1/images/keyframe/s1.png"
