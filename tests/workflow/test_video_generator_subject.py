import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _look(front="fk", side="sk", back=None):
    m = MagicMock()
    m.id = "l1"
    m.is_default = True
    m.front_key = front
    m.side_key = side
    m.back_key = back
    return m


def _state():
    return {
        "video_provider": "seedance", "resolution": None, "project_id": "p1", "episode_id": "e1",
        "video_model": "m", "videos": [], "look_assignments": {"1": {"林夏": "l1"}},
        "shots": [{"shot_id": "s1", "scene_number": 1, "duration_seconds": 5, "characters": ["林夏"]}],
        "prompts": [{"shot_id": "s1", "prompt_text": "hero", "negative_prompt": "",
                     "reference_image_url": None, "reference_role": None, "edited_prompt": None,
                     "keyframe_url": None}],
    }


@pytest.mark.asyncio
async def test_video_generator_appends_subject_refs_from_assigned_look():
    import drama_agent.workflow.nodes.video_generator as vg
    ch = MagicMock()
    ch.id = "c1"
    ch.name = "林夏"
    fake = MagicMock()
    fake.create_task = AsyncMock(return_value="t1")
    fake.wait_for_task = AsyncMock(return_value=MagicMock(
        status="succeeded", video_url="http://v.mp4", last_frame_url=None))
    with patch.object(vg.video_service, "get_provider", return_value=fake), \
         patch.object(vg.storage_service, "get_project_output_dir", return_value=MagicMock()), \
         patch.object(vg.storage_service, "download_file", AsyncMock()), \
         patch.object(vg, "AsyncSessionLocal", MagicMock()), \
         patch("drama_agent.services.character_entity_service.get_character_by_name",
               AsyncMock(return_value=ch)), \
         patch("drama_agent.services.character_entity_service.list_looks",
               AsyncMock(return_value=[_look(front="fk", side="sk", back=None)])):
        await vg.video_generator_node(_state())
    refs = fake.create_task.call_args.kwargs["references"]
    subj = [r for r in refs if r.kind == "subject"]
    # 该角色本场景 Look 的 front/side(back 为空跳过)→ 2 张 subject,带视图 URL
    assert len(subj) == 2
    urls = {r.url for r in subj}
    assert "/api/characters/view/fk" in urls and "/api/characters/view/sk" in urls
    assert all(r.subject_name == "林夏" for r in subj)


@pytest.mark.asyncio
async def test_video_generator_no_character_entity_skips_subject():
    """名字 join 不到 Character → 不注入 subject,不报错(退化为仅文本一致)。"""
    import drama_agent.workflow.nodes.video_generator as vg
    fake = MagicMock()
    fake.create_task = AsyncMock(return_value="t1")
    fake.wait_for_task = AsyncMock(return_value=MagicMock(
        status="succeeded", video_url="http://v.mp4", last_frame_url=None))
    with patch.object(vg.video_service, "get_provider", return_value=fake), \
         patch.object(vg.storage_service, "get_project_output_dir", return_value=MagicMock()), \
         patch.object(vg.storage_service, "download_file", AsyncMock()), \
         patch.object(vg, "AsyncSessionLocal", MagicMock()), \
         patch("drama_agent.services.character_entity_service.get_character_by_name",
               AsyncMock(return_value=None)):
        await vg.video_generator_node(_state())
    refs = fake.create_task.call_args.kwargs["references"]
    assert [r for r in refs if r.kind == "subject"] == []
