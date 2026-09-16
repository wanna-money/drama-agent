"""video_generator_node 的裁剪触发条件:生成时长 > 叙事时长就裁剪(默认路径,
不再依赖一个可选的 narrative_duration_seconds 字段)。
"""
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from drama_agent.workflow.nodes import video_generator as vg


@dataclass
class _FakeTaskResult:
    status: str = "succeeded"
    video_url: str | None = "http://example.com/v.mp4"
    last_frame_url: str | None = None
    seed: int | None = None
    revised_prompt: str | None = None
    error: str | None = None


def _base_state(shot_duration: int, generation_duration: int) -> dict:
    shot_id = "shot-1"
    return {
        "project_id": "p1",
        "episode_id": "e1",
        "video_provider": "seedance",
        "video_model": "seedance",
        "aspect_ratio": "9:16",
        "resolution": None,
        "shots": [{
            "shot_id": shot_id,
            "duration_seconds": shot_duration,
            "characters": [],
        }],
        "prompts": [{
            "shot_id": shot_id,
            "prompt_text": "a scene",
            "negative_prompt": "",
            "reference_image_url": None,
            "reference_role": None,
            "approved": True,
            "edited_prompt": None,
            "edited_negative_prompt": None,
            "keyframe_url": None,
            "generation_duration_seconds": generation_duration,
        }],
        "videos": [],
    }


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    """跟裁剪判定无关的旁路(进度上报、产物树、计费、下载)一律 no-op,让测试只盯
    trim_to_narrative_duration 是否被正确调用。"""
    monkeypatch.setattr(vg, "report_progress", AsyncMock(return_value=None))
    monkeypatch.setattr(
        vg.storage_service, "download_file", AsyncMock(return_value="local"))
    monkeypatch.setattr(
        vg.usage_service, "record_video", AsyncMock(return_value=None))
    monkeypatch.setattr(
        vg.subject_ref_service, "subject_refs", AsyncMock(return_value=[]))

    class _NoopSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(vg, "AsyncSessionLocal", lambda: _NoopSession())
    monkeypatch.setattr(
        vg.artifact_service, "create_root", AsyncMock(return_value=None))


def _mock_provider():
    provider = AsyncMock()
    provider.create_task = AsyncMock(return_value="task-1")
    provider.wait_for_task = AsyncMock(return_value=_FakeTaskResult())
    return provider


@pytest.mark.asyncio
async def test_trims_when_generation_duration_exceeds_narrative_duration():
    """叙事时长 2s,生成时长(模型下限抬高后)5s —— 生成的素材比叙事时长长,
    必须触发裁剪,且裁到叙事时长。"""
    provider = _mock_provider()
    trim = AsyncMock(return_value=None)
    with patch.object(vg.video_service, "get_provider", return_value=provider), \
         patch.object(vg, "trim_to_narrative_duration", trim):
        await vg.video_generator_node(_base_state(shot_duration=2, generation_duration=5))

    trim.assert_awaited_once()
    args, _ = trim.call_args
    assert args[1] == 2
    # 提交给 provider 的生成时长必须是抬高后的值,不是叙事时长
    _, kwargs = provider.create_task.call_args
    assert kwargs["duration"] == 5


@pytest.mark.asyncio
async def test_does_not_trim_when_generation_duration_equals_narrative_duration():
    """叙事时长与生成时长相等(模型下限本就满足叙事意图)时不需要裁剪。"""
    provider = _mock_provider()
    trim = AsyncMock(return_value=None)
    with patch.object(vg.video_service, "get_provider", return_value=provider), \
         patch.object(vg, "trim_to_narrative_duration", trim):
        await vg.video_generator_node(_base_state(shot_duration=5, generation_duration=5))

    trim.assert_not_awaited()
