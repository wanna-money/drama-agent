"""从素材库人物 Asset 导入到项目角色 Look:读图 → 切四视图 → 填 Look 四 key。"""
from __future__ import annotations

from typing import Any

from drama_agent.db.enums import CharacterView
from drama_agent.services import asset_service, character_entity_service
from drama_agent.services.character_gen_service import crop_four_views


async def import_asset_as_look_views(look_id: str, asset_id: str) -> Any | None:
    """把素材图(四视图长图)切成四视图填入 Look。

    asset 不存在 → ValueError;look 不存在 → None(调用方转 404)。返回更新后的 Look 行。
    """
    content = await asset_service.read_asset_bytes(asset_id)
    if content is None:
        raise ValueError("素材不存在")
    front, side, back, face = crop_four_views(content)
    views = [
        (CharacterView.FRONT.value, front),
        (CharacterView.SIDE.value, side),
        (CharacterView.BACK.value, back),
        (CharacterView.FACE.value, face),
    ]
    row = None
    for view, block in views:
        row = await character_entity_service.set_view(
            look_id, view, block, f"{view}.png", "image/png")
        if row is None:
            return None
    return row
