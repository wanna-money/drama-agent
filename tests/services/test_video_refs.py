import pytest
from unittest.mock import AsyncMock, MagicMock


def test_designate_prompt_numbers_refs():
    from drama_agent.services.video_refs import RefImage, designate_prompt

    refs = [
        RefImage(url="k0", kind="first_frame"),
        RefImage(url="k1", kind="subject", subject_name="林夏", view="front"),
    ]
    out = designate_prompt("跳舞", refs)
    assert "参考图1为开场画面" in out and "参考图2为角色「林夏」正面" in out
    assert out.startswith("跳舞")


def test_cap_refs_keeps_first_frame_and_warns(caplog):
    from drama_agent.services.video_refs import RefImage, cap_refs

    refs = [RefImage(url=f"s{i}", kind="subject") for i in range(10)]
    refs.append(RefImage(url="ff", kind="first_frame"))
    kept = cap_refs(refs, 9, "seedance")
    assert len(kept) == 9
    assert any(r.kind == "first_frame" for r in kept)  # 首帧优先保留


def test_reference_content_items_shape():
    from drama_agent.services.video_refs import RefImage, reference_content_items

    items = reference_content_items([RefImage(url="u1", kind="subject")])
    assert items == [{"type": "image_url", "image_url": {"url": "u1"}, "role": "reference_image"}]


@pytest.mark.asyncio
async def test_seedance_multi_ref_uses_reference_mode_and_designation():
    """有 subject 参考图 → 全模态参考模式：全部 reference_image + prompt 追加指派。"""
    from drama_agent.services.video_service import SeedanceVideoService
    from drama_agent.services.video_refs import RefImage

    svc = SeedanceVideoService.__new__(SeedanceVideoService)  # 跳过 __init__（不建 Ark client）
    svc.model = "m"
    captured = {}

    async def fake_create(**kw):
        captured.update(kw)
        return MagicMock(id="t1")

    svc._client = MagicMock()
    svc._client.content_generation.tasks.create = AsyncMock(side_effect=fake_create)
    tid = await svc.create_task(
        prompt="跳舞",
        references=[
            RefImage(url="ff", kind="first_frame"),
            RefImage(url="c1", kind="subject", subject_name="林夏", view="front"),
        ],
    )
    assert tid == "t1"
    content = captured["content"]
    imgs = [c for c in content if c["type"] == "image_url"]
    assert len(imgs) == 2 and all(c["role"] == "reference_image" for c in imgs)
    assert "参考图1为开场画面" in content[0]["text"]  # 指派进了 prompt


@pytest.mark.asyncio
async def test_seedance_single_first_frame_keeps_first_frame_mode():
    """仅一张首帧、无 subject → 保持首帧模式（role=first_frame），不改旧行为。"""
    from drama_agent.services.video_service import SeedanceVideoService
    from drama_agent.services.video_refs import RefImage

    svc = SeedanceVideoService.__new__(SeedanceVideoService)
    svc.model = "m"
    captured = {}
    svc._client = MagicMock()
    svc._client.content_generation.tasks.create = AsyncMock(
        side_effect=lambda **kw: (captured.update(kw) or MagicMock(id="t1"))
    )
    await svc.create_task(prompt="p", references=[RefImage(url="ff", kind="first_frame")])
    imgs = [c for c in captured["content"] if c["type"] == "image_url"]
    assert imgs == [{"type": "image_url", "image_url": {"url": "ff"}, "role": "first_frame"}]


@pytest.mark.asyncio
async def test_seedance_backward_compat_single_url():
    """旧参数 reference_image_url（video_actions 用）仍生效。"""
    from drama_agent.services.video_service import SeedanceVideoService

    svc = SeedanceVideoService.__new__(SeedanceVideoService)
    svc.model = "m"
    captured = {}
    svc._client = MagicMock()
    svc._client.content_generation.tasks.create = AsyncMock(
        side_effect=lambda **kw: (captured.update(kw) or MagicMock(id="t1"))
    )
    await svc.create_task(prompt="p", reference_image_url="ff", reference_role="first_frame")
    imgs = [c for c in captured["content"] if c["type"] == "image_url"]
    assert imgs and imgs[0]["image_url"]["url"] == "ff"
