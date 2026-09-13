"""参考素材送达:本地存储 ref 转 base64 data URI,让外部 video provider 能取到。

按 url scheme 分流,不假设 local backend:
- 相对 `/api/characters/(view|voice)/{key}`(local backend 产)→ 读存储字节 → data URI。
- 相对 `/api/projects/{pid}/images/{type}/{name}`(上传/素材库拷贝/项目已有)→ 读盘 → data URI。
- `http(s)://`(将来 OSS 直链)/ 已是 `data:` → 原样透传。

**新增一种本地 URL 形态时必须同步登记在此**:未登记的相对 URL 会被原样发给 provider,
而它取不到 —— 参考图静默失效,界面上看不出任何差别。

视频参考走**另一条路**:平台对视频只接受公网 URL / asset://ID,没有 base64
那条路,故它由公网存储现签,不进内联。
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import replace
from pathlib import Path

from drama_agent.config import settings
from drama_agent.services.asset_storage import get_asset_storage
from drama_agent.services.audio_validate import audio_mime
from drama_agent.services.public_storage import (
    PublicStorageUnavailable,
    get_public_storage,
)
from drama_agent.services.storage_service import storage_service
from drama_agent.services.video_refs import RefAudio, RefImage, RefVideo

logger = logging.getLogger(__name__)

_VIEW_PREFIX = "/api/characters/view/"
_VOICE_PREFIX = "/api/characters/voice/"
_PROJECT_IMG_PREFIX = "/api/projects/"


def _project_image_path(url: str) -> Path | None:
    """`/api/projects/{pid}/images/{type}/{name}` → 磁盘路径;不是该形态返回 None。

    每段都来自客户端拼出的 URL,故逐段校验(非空、非 `.`/`..`、不含分隔符)
    后再落盘,不能只靠 resolve 后的 `is_relative_to` 兜底:`..` 出现在中间段时
    ``pid/../images/...`` 这类路径仍会 resolve 回 upload_dir 内部,骗过那道检查。
    """
    rest = url[len(_PROJECT_IMG_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 4 or parts[1] != "images":
        return None
    pid, _, image_type, name = parts
    if any(seg in ("", ".", "..") or "/" in seg or "\\" in seg
           for seg in (pid, image_type, name)):
        raise ValueError(f"非法的参考图路径: {url}")
    root = Path(storage_service.upload_dir).resolve()
    target = (root / pid / image_type / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"非法的参考图路径: {url}")
    return target


async def _inline_image(url: str) -> str:
    if url.startswith(_VIEW_PREFIX):
        raw = await get_asset_storage().read(url[len(_VIEW_PREFIX):])
        return f"data:image/png;base64,{base64.b64encode(raw).decode()}"
    if url.startswith(_PROJECT_IMG_PREFIX):
        path = _project_image_path(url)
        if path is None:
            return url
        if not path.is_file():
            raise FileNotFoundError(f"参考图文件不存在: {url}")
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
    return url


async def _inline_audio(url: str) -> str:
    if url.startswith(_VOICE_PREFIX):
        raw = await get_asset_storage().read(url[len(_VOICE_PREFIX):])
        return f"data:{audio_mime(url)};base64,{base64.b64encode(raw).decode()}"
    return url


async def inline_local_refs(
    refs: list[RefImage], audio_refs: list[RefAudio]
) -> tuple[list[RefImage], list[RefAudio]]:
    out_imgs = [replace(r, url=await _inline_image(r.url)) for r in refs]
    out_auds = [replace(a, url=await _inline_audio(a.url)) for a in audio_refs]
    return out_imgs, out_auds


async def _read_local_image(url: str) -> tuple[bytes, str] | None:
    """本地图片 URL → (字节, 文件名);不是本地形态返回 None(调用方原样透传)。"""
    if url.startswith(_VIEW_PREFIX):
        key = url[len(_VIEW_PREFIX):]
        return await get_asset_storage().read(key), key
    if url.startswith(_PROJECT_IMG_PREFIX):
        path = _project_image_path(url)
        if path is None or not path.is_file():
            return None
        return path.read_bytes(), path.name
    return None


def _sign_video(url: str) -> str:
    """storage key → 预签名公网 URL;已是 http(s)/asset:// 的原样透传。

    现签而非存签好的 URL:预签名有有效期,存下来的那一份会在到期后腐烂成
    一个看着正常、实际 403 的字符串。签名是纯计算,每次现签没有成本。
    """
    if url.startswith(("http://", "https://", "asset://", "data:")):
        return url
    return get_public_storage().signed_url(url)


async def _public_image(url: str) -> str | None:
    """本地图片 → 上传到公网并现签;非本地或读不到返回 None(调用方退回内联)。"""
    got = await _read_local_image(url)
    if got is None:
        return None
    content, name = got
    storage = get_public_storage()
    return storage.signed_url(await storage.put(content, name))


async def deliver_refs(
    refs: list[RefImage],
    audio_refs: list[RefAudio],
    video_refs: list[RefVideo] | None = None,
) -> tuple[list[RefImage], list[RefAudio], list[RefVideo]]:
    """把语义 ref 变成 provider 真正能取到的形态。

    图片/音频按 settings.ref_delivery_mode 分流;**视频恒走公网**(无 base64 路径)。
    public 模式下存储不可用时图片退回 base64 —— 它本来就有那条路,
    让整支散片失败是不必要的。
    """
    videos = [replace(v, url=_sign_video(v.url)) for v in (video_refs or [])]

    if settings.ref_delivery_mode == "public":
        try:
            out_imgs = []
            for r in refs:
                public = await _public_image(r.url)
                out_imgs.append(replace(r, url=public) if public
                                else replace(r, url=await _inline_image(r.url)))
            out_auds = [replace(a, url=await _inline_audio(a.url)) for a in audio_refs]
            return out_imgs, out_auds, videos
        except PublicStorageUnavailable:
            logger.warning("ref_delivery_mode=public 但公网存储不可用,退回 base64")

    out_imgs = [replace(r, url=await _inline_image(r.url)) for r in refs]
    out_auds = [replace(a, url=await _inline_audio(a.url)) for a in audio_refs]
    return out_imgs, out_auds, videos
