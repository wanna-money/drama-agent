"""视频参考图的 provider 无关语义模型 + 多图参考公共翻译工具。

workflow 只表达语义（RefImage）；各 video provider 用这里的工具翻译成自家 API。
平台差异（能力上限/模式）吸收在 provider.create_task。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

RefKind = Literal["first_frame", "subject", "last_frame"]
_VIEW_CN = {"front": "正面", "side": "侧面", "back": "背面"}


@dataclass
class RefImage:
    url: str  # 公网 URL / asset://ID / data:base64
    kind: RefKind
    subject_name: str | None = None
    view: str | None = None


@dataclass
class RefAudio:
    url: str  # 本地 /api/characters/voice/{key} / 公网 URL / data:audio;base64
    subject_name: str | None = None


@dataclass
class RefVideo:
    """参考视频。

    **url 只能是公网 URL 或 asset://ID** —— 平台对视频不接受 base64
    (图片和音频都接受)。故它不进 ref_delivery.inline_local_refs 那条内联路径,
    而是由公网存储的 signed_url 现签出来。
    """

    url: str
    subject_name: str | None = None
    # 该支视频的时长(秒)。接口层用它做总时长求和校验;provider 侧不发送它 ——
    # 留在 dataclass 里是为了让"接口收下的字段集"与"运行时重建的字段集"一致,
    # 否则 video_refs_json 原样重建就会炸(字段只加一侧 = 接缝漏洞)。
    duration: int | None = None


def cap_refs(refs: list[RefImage], max_images: int, provider: str) -> list[RefImage]:
    """按上限裁剪；first_frame 优先保留；超限记 warning（不静默）。"""
    if len(refs) <= max_images:
        return refs
    ordered = sorted(refs, key=lambda r: 0 if r.kind == "first_frame" else 1)
    logger.warning("video refs capped for %s: %d -> %d", provider, len(refs), max_images)
    return ordered[:max_images]


def reference_content_items(refs: list[RefImage]) -> list[dict[str, Any]]:
    """转成全模态参考/r2va 的 content 图片项（role 统一 reference_image）。"""
    return [
        {"type": "image_url", "image_url": {"url": r.url}, "role": "reference_image"} for r in refs
    ]


def audio_content_items(audios: list[RefAudio]) -> list[dict[str, Any]]:
    """转成全模态/多模态参考的 content 音频项（role 统一 reference_audio）。"""
    return [
        {"type": "audio_url", "audio_url": {"url": a.url}, "role": "reference_audio"}
        for a in audios
    ]


def video_content_items(videos: list[RefVideo]) -> list[dict[str, Any]]:
    """转成全模态参考的 content 视频项(role 统一 reference_video)。"""
    return [
        {"type": "video_url", "video_url": {"url": v.url}, "role": "reference_video"}
        for v in videos
    ]


def cap_audio_refs(audios: list[RefAudio], max_audios: int, provider: str) -> list[RefAudio]:
    """按 provider 音频上限截断；超限记 warning（不静默）。"""
    if len(audios) <= max_audios:
        return audios
    logger.warning("audio refs capped for %s: %d -> %d", provider, len(audios), max_audios)
    return audios[:max_audios]


def cap_video_refs(videos: list[RefVideo], max_videos: int, provider: str) -> list[RefVideo]:
    """按 provider 视频上限截断;超限记 warning(不静默)。"""
    if len(videos) <= max_videos:
        return videos
    logger.warning("video refs capped for %s: %d -> %d", provider, len(videos), max_videos)
    return videos[:max_videos]


def append_negative(prompt: str, negative_prompt: str) -> str:
    """把负向提示折进 prompt 文本(供无独立 negative 字段的 provider 用)。

    Seedance / MiniMax 的 API 都没有 negative_prompt 字段。收下这个参数却不落到请求里,
    等于用户在界面上改了负向提示、实际请求毫无变化 —— 那比不提供该输入框更糟。
    """
    neg = (negative_prompt or "").strip()
    if not neg:
        return prompt
    return f"{prompt}（避免出现：{neg}）"


def designate_prompt(
    prompt: str, refs: list[RefImage], audio_refs: list[RefAudio] | None = None,
    video_refs: list[RefVideo] | None = None,
) -> str:
    """在 prompt 末尾按顺序追加文字指派(全模态/多模态参考模式需要):先图片、后视频、再音色。

    编号必须与 content 里素材的出现顺序一致 —— 手册要求 prompt 用 @image1 / @video1
    这类指代,编号错位会让"改视频1"作用到另一支上。
    """
    parts: list[str] = []
    for i, r in enumerate(refs, start=1):
        if r.kind == "first_frame":
            parts.append(f"参考图{i}为开场画面（首帧）")
        elif r.kind == "last_frame":
            parts.append(f"参考图{i}为结束画面（尾帧）")
        else:
            who = r.subject_name or "主体"
            view_cn = _VIEW_CN.get(r.view or "", "")
            parts.append(f"参考图{i}为角色「{who}」{view_cn}参考")
    for k, v in enumerate(video_refs or [], start=1):
        who = f"「{v.subject_name}」" if v.subject_name else ""
        parts.append(f"参考视频{k}{who}")
    for j, a in enumerate(audio_refs or [], start=1):
        who = a.subject_name or "该角色"
        parts.append(f"使用 @音频{j} 的音色为角色「{who}」配音")
    if not parts:
        return prompt
    return f"{prompt}（{'；'.join(parts)}）"


def merge_legacy_ref(
    references: list[RefImage] | None, reference_image_url: str | None, reference_role: str | None
) -> list[RefImage]:
    """向后兼容：把旧的单张 reference_image_url 并入 references。role→kind 映射。"""
    refs = list(references or [])
    if reference_image_url and not refs:
        kind: RefKind = (
            "subject"
            if reference_role == "subject_reference"
            else ("last_frame" if reference_role == "last_frame" else "first_frame")
        )
        refs = [RefImage(url=reference_image_url, kind=kind)]
    return refs
