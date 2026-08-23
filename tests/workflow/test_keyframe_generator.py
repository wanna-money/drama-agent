import pytest
from unittest.mock import AsyncMock, patch


def _state():
    return {
        "project_id": "p1", "keyframe_image_model": "doubao-seedream-3-0-t2i",
        "shots": [{"shot_id": "s1"}, {"shot_id": "s2"}],
        "prompts": [
            {"shot_id": "s1", "prompt_text": "hero", "edited_prompt": None, "keyframe_url": None},
            {"shot_id": "s2", "prompt_text": "villain", "edited_prompt": None, "keyframe_url": None},
        ],
    }


@pytest.mark.asyncio
async def test_keyframe_generator_sets_url_per_prompt():
    import drama_agent.workflow.nodes.keyframe_generator as kg
    with patch.object(kg.asset_gen_service, "generate_image", AsyncMock(return_value=[b"IMG"])), \
         patch.object(kg.storage_service, "save_project_image",
                      AsyncMock(return_value=("s1.png", "/abs/s1.png"))):
        out = await kg.keyframe_generator_node(_state())
    urls = [p["keyframe_url"] for p in out["prompts"]]
    assert all(u and "/images/keyframe/" in u for u in urls)


@pytest.mark.asyncio
async def test_keyframe_generator_skips_existing():
    import drama_agent.workflow.nodes.keyframe_generator as kg
    st = _state()
    st["prompts"][0]["keyframe_url"] = "/api/projects/p1/images/keyframe/old.png"
    gen = AsyncMock(return_value=[b"IMG"])
    with patch.object(kg.asset_gen_service, "generate_image", gen), \
         patch.object(kg.storage_service, "save_project_image",
                      AsyncMock(return_value=("s2.png", "/abs/s2.png"))):
        out = await kg.keyframe_generator_node(st)
    assert out["prompts"][0]["keyframe_url"] == "/api/projects/p1/images/keyframe/old.png"  # 保留
    assert gen.await_count == 1  # 只给 s2 生成


@pytest.mark.asyncio
async def test_keyframe_generator_single_failure_isolated():
    import drama_agent.workflow.nodes.keyframe_generator as kg

    async def flaky(model, prompt, **kw):
        if "hero" in prompt:
            raise RuntimeError("boom")
        return [b"IMG"]

    with patch.object(kg.asset_gen_service, "generate_image", AsyncMock(side_effect=flaky)), \
         patch.object(kg.storage_service, "save_project_image",
                      AsyncMock(return_value=("s2.png", "/abs/s2.png"))):
        out = await kg.keyframe_generator_node(_state())
    assert out["prompts"][0]["keyframe_url"] is None      # s1 失败 → 无 url,不崩
    assert out["prompts"][1]["keyframe_url"] is not None   # s2 正常
