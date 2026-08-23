from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image, ImageDraw


def _sheet_with_gaps() -> bytes:
    """白底 300x100,三块黑竖条,块间留白隙 → 空隙检测应切成 3。"""
    img = Image.new("RGB", (300, 100), "white")
    d = ImageDraw.Draw(img)
    for x0 in (10, 110, 210):
        d.rectangle([x0, 20, x0 + 70, 80], fill="black")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_generate_three_view_sheet_crops_gen_output():
    from drama_agent.services import character_gen_service as g
    with patch("drama_agent.services.character_gen_service.asset_gen_service.generate_image",
               AsyncMock(return_value=[_sheet_with_gaps()])):
        parts = await g.generate_four_view_sheet("女主林夏", "日常装", "doubao-seedream-3-0-t2i")
    assert len(parts) == 4 and all(p for p in parts)


@pytest.mark.asyncio
async def test_generate_three_view_sheet_empty_raises():
    from drama_agent.services import character_gen_service as g
    with patch("drama_agent.services.character_gen_service.asset_gen_service.generate_image",
               AsyncMock(return_value=[])):
        with pytest.raises(ValueError):
            await g.generate_four_view_sheet("x", "y", "m")
