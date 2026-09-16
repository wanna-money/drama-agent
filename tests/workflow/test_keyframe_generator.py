"""keyframe_generator_node 必须把作品级 visual_style 传给生图,否则关键帧的风格
保证退化成"指望 LLM 把风格话写进 prompt_text"的软约束(见 prompt_engineer),
而角色立绘/素材库生图都走的是确定性拼接兜底(asset_gen_service.generate_image)。
"""
from unittest.mock import AsyncMock, patch

import pytest

from drama_agent.workflow.nodes.keyframe_generator import keyframe_generator_node


def _prompt(shot_id="s1", keyframe_url=None):
    return {
        "shot_id": shot_id,
        "prompt_text": "a scene",
        "negative_prompt": "",
        "reference_image_url": None,
        "reference_role": None,
        "approved": False,
        "edited_prompt": None,
        "edited_negative_prompt": None,
        "keyframe_url": keyframe_url,
        "generation_duration_seconds": 5,
    }


@pytest.mark.asyncio
async def test_keyframe_generator_passes_visual_style_to_generate_image():
    state = {
        "project_id": "p1",
        "visual_style": "guoman",
        "prompts": [_prompt()],
    }
    with patch(
        "drama_agent.workflow.nodes.keyframe_generator.asset_gen_service.generate_image",
        AsyncMock(return_value=[b"img"]),
    ) as mock_gen, patch(
        "drama_agent.workflow.nodes.keyframe_generator.storage_service.save_project_image",
        AsyncMock(return_value=("s1.png", "")),
    ):
        await keyframe_generator_node(state)

    assert mock_gen.call_args.kwargs["visual_style"] == "guoman"


@pytest.mark.asyncio
async def test_keyframe_generator_skips_shots_with_existing_keyframe():
    state = {
        "project_id": "p1",
        "visual_style": "guoman",
        "prompts": [_prompt(keyframe_url="/existing.png")],
    }
    with patch(
        "drama_agent.workflow.nodes.keyframe_generator.asset_gen_service.generate_image",
        AsyncMock(return_value=[b"img"]),
    ) as mock_gen:
        result = await keyframe_generator_node(state)

    mock_gen.assert_not_called()
    assert result["prompts"][0]["keyframe_url"] == "/existing.png"
