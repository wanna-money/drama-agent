"""音频上传校验:格式 wav/mp3、大小 ≤15MB、时长 2–15s(mutagen 读,不依赖 ffmpeg 二进制)。"""
from __future__ import annotations

import io
from pathlib import Path

_ALLOWED_EXT = {".wav", ".mp3"}
_MAX_BYTES = 15 * 1024 * 1024
_MIN_SEC = 2.0
_MAX_SEC = 15.0
_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


def audio_mime(key: str) -> str:
    return _MIME.get(Path(key).suffix.lower(), "application/octet-stream")


def validate_audio(content: bytes, filename: str, content_type: str | None) -> None:
    """不合规抛 ValueError(带明确中文原因);调用方(API)映射为 422。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError(f"仅支持 wav/mp3 音频,收到「{ext or '未知格式'}」")
    if len(content) > _MAX_BYTES:
        raise ValueError(f"音频不得超过 15MB(当前约 {len(content) // 1024 // 1024}MB)")
    import mutagen
    try:
        mf = mutagen.File(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"音频解析失败:{e}") from e
    info = getattr(mf, "info", None)
    if mf is None or info is None:
        raise ValueError("无法识别音频,请上传标准 wav/mp3")
    dur = float(info.length)
    if dur < _MIN_SEC or dur > _MAX_SEC:
        raise ValueError(f"音频时长须在 2–15 秒之间(当前 {dur:.1f} 秒)")
