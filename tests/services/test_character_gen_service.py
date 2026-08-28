from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image, ImageDraw


def _sheet_with_gaps() -> bytes:
    """白底 400x100,**四**块黑竖条 → 恰好 3 条内部留白间隔,自动裁切应成功。

    必须给足 4 块:只画 3 块的话内部仅 2 条空隙,测的就不是真实的空隙切分。
    """
    img = Image.new("RGB", (400, 100), "white")
    d = ImageDraw.Draw(img)
    for x0 in (10, 110, 210, 310):
        d.rectangle([x0, 20, x0 + 70, 80], fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sheet_without_enough_gaps() -> bytes:
    """复现用户那张 sheet 的失败形状:最右侧图块贴到右边缘,与相邻块的留白连成一片,
    内部只剩 2 条空隙 —— 静默等分成四份就会切歪、把半张相邻视图带进来。"""
    img = Image.new("RGB", (300, 100), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([10, 20, 60, 80], fill="black")     # 第一块
    d.rectangle([100, 20, 150, 80], fill="black")   # 第二块
    d.rectangle([190, 20, 299, 80], fill="black")   # 第三块直抵右边缘 → 少一条内部空隙
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_crop_raises_instead_of_guessing_equal_quarters():
    """空隙不足 3 条时必须显式失败。退化成等分四份会让"侧面/背面"里混进
    半张相邻视图,而错切与正切在返回值里无法区分 —— 这条删掉就放走该回归。"""
    from drama_agent.services import character_gen_service as g
    with pytest.raises(g.CropFailed):
        g.crop_four_views(_sheet_without_enough_gaps())


@pytest.mark.asyncio
async def test_generate_three_view_sheet_crops_gen_output():
    from drama_agent.services import character_gen_service as g
    with patch("drama_agent.services.character_gen_service.asset_gen_service.generate_image",
               AsyncMock(return_value=[_sheet_with_gaps()])):
        sheet, parts = await g.generate_four_view_sheet(
            "女主林夏", "日常装", "doubao-seedream-3-0-t2i")
    assert sheet
    assert parts is not None and len(parts) == 4 and all(p for p in parts)


@pytest.mark.asyncio
async def test_generate_returns_sheet_with_none_views_when_crop_fails():
    """裁切失败不能让整次生成报废 —— 必须把原图交回去供人工裁切,否则用户得重烧一次生成。"""
    from drama_agent.services import character_gen_service as g
    bad = _sheet_without_enough_gaps()
    with patch("drama_agent.services.character_gen_service.asset_gen_service.generate_image",
               AsyncMock(return_value=[bad])):
        sheet, parts = await g.generate_four_view_sheet("x", "y", "m")
    assert sheet == bad
    assert parts is None


@pytest.mark.asyncio
async def test_generate_three_view_sheet_empty_raises():
    from drama_agent.services import character_gen_service as g
    with patch("drama_agent.services.character_gen_service.asset_gen_service.generate_image",
               AsyncMock(return_value=[])):
        with pytest.raises(ValueError):
            await g.generate_four_view_sheet("x", "y", "m")
