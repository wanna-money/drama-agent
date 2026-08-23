"""参考素材送达:本地存储 ref 转 base64 data URI,让外部 video provider 能取到。

按 url scheme 分流,不假设 local backend:
- 相对 `/api/characters/(view|voice)/{key}`(local backend 产)→ 读存储字节 → data URI。
- `http(s)://`(将来 OSS 直链)/ 已是 `data:` → 原样透传。
读字节走 get_asset_storage() 工厂,切 OSS/CFS 后本 helper 零改。
"""
from __future__ import annotations

import base64
from dataclasses import replace

from drama_agent.services.asset_storage import get_asset_storage
from drama_agent.services.audio_validate import audio_mime
from drama_agent.services.video_refs import RefAudio, RefImage

_VIEW_PREFIX = "/api/characters/view/"
_VOICE_PREFIX = "/api/characters/voice/"


async def _inline(url: str, mime: str) -> str:
    """相对本地 ref → data URI;http(s)/data: 原样返回。"""
    if url.startswith(_VIEW_PREFIX):
        key = url[len(_VIEW_PREFIX):]
    elif url.startswith(_VOICE_PREFIX):
        key = url[len(_VOICE_PREFIX):]
    else:
        return url
    raw = await get_asset_storage().read(key)
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


async def inline_local_refs(
    refs: list[RefImage], audio_refs: list[RefAudio]
) -> tuple[list[RefImage], list[RefAudio]]:
    out_imgs = [replace(r, url=await _inline(r.url, "image/png")) for r in refs]
    out_auds = [
        replace(a, url=await _inline(a.url, audio_mime(a.url))) for a in audio_refs
    ]
    return out_imgs, out_auds
