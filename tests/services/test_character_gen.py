from io import BytesIO

import pytest
from PIL import Image


def _sheet_with_gaps() -> bytes:
    img = Image.new("RGB", (800, 100), (255, 255, 255))
    px = img.load()
    for x0, x1 in [(0, 150), (200, 350), (400, 550), (600, 750)]:
        for x in range(x0, x1):
            for y in range(30, 70):
                px[x, y] = (0, 0, 0)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_crop_four_views_splits_into_four():
    from drama_agent.services.character_gen_service import crop_four_views
    parts = crop_four_views(_sheet_with_gaps())
    assert len(parts) == 4
    widths = [Image.open(BytesIO(p)).size[0] for p in parts]
    assert all(w > 0 for w in widths)


def test_crop_four_views_raises_when_no_gaps():
    """无留白可分时必须抛错。等分四份时,等分线与真实人物位置不符会把相邻视图
    切进同一张图,且错切与正切在返回值里无法区分。"""
    from drama_agent.services.character_gen_service import CropFailed, crop_four_views
    solid = Image.new("RGB", (400, 100), (0, 0, 0))
    buf = BytesIO()
    solid.save(buf, format="PNG")
    with pytest.raises(CropFailed):
        crop_four_views(buf.getvalue())


@pytest.mark.asyncio
async def test_generate_four_view_sheet_returns_sheet_and_four(monkeypatch):
    from unittest.mock import AsyncMock

    from drama_agent.services import character_gen_service as cg
    monkeypatch.setattr(cg.asset_gen_service, "generate_image",
                        AsyncMock(return_value=[_sheet_with_gaps()]))
    sheet, parts = await cg.generate_four_view_sheet("林夏", "红裙", "seedream")
    assert sheet
    assert parts is not None and len(parts) == 4


def test_sheet_prompt_mentions_four_views():
    from drama_agent.services.character_gen_service import _sheet_prompt
    p = _sheet_prompt("林夏", "红裙")
    assert "面部特写" in p and "正面" in p and "侧面" in p and "背面" in p
