"""上传视频校验:格式 mp4/mov、大小 ≤200MB、时长 2–30s、FPS 24–60、分辨率 ≤720p。

**没装 ffprobe 时放行**,只校验格式与大小并返回 warning。理由:装不装 ffmpeg 是
环境问题,而绝大多数手机拍的 mp4 本就合规 —— 拒绝上传比放行更糟。放行 + 明示
未校验,让平台做最终裁决(这与我们对人脸的处理一致:不自己拦,透出平台原因)。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

_ALLOWED_EXT = {".mp4", ".mov"}
_MAX_BYTES = 200 * 1024 * 1024
# 手册:非视频编辑任务 [2,30]s;视频编辑任务 [4,30]s。此处按宽的一侧收,
# 编辑任务那条 4s 下限由接口层结合 task_type 判(上传时还不知道要拿它做什么)。
_MIN_SEC = 2.0
_MAX_SEC = 30.0
_MIN_FPS = 24.0
_MAX_FPS = 60.0
_MAX_HEIGHT = 720
_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime"}

_NO_FFPROBE_WARNING = (
    "未安装 ffmpeg,无法校验时长/帧率/分辨率;若不符合平台要求会在生成时被拒"
    "(macOS: brew install ffmpeg;Debian/Ubuntu: apt install ffmpeg)"
)


def video_mime(filename: str) -> str:
    return _MIME.get(Path(filename).suffix.lower(), "application/octet-stream")


def _probe(content: bytes) -> dict:
    """用 ffprobe 读时长/帧率/高度。未装 ffprobe 时抛 FileNotFoundError。"""
    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        f.write(content)
        f.flush()
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate,height:format=duration",
             "-of", "json", f.name],
            capture_output=True, check=True, timeout=30,
        ).stdout
    data = json.loads(out or "{}")
    stream = (data.get("streams") or [{}])[0]
    raw_fps = stream.get("avg_frame_rate") or "0/1"
    num, _, den = raw_fps.partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    return {
        "duration": float((data.get("format") or {}).get("duration") or 0),
        "fps": fps,
        "height": int(stream.get("height") or 0),
    }


def validate_video(content: bytes, filename: str) -> dict:
    """不合规抛 ValueError(带明确中文原因);调用方(API)映射为 422。

    返回 {"duration": int | None, "warning": str | None}。duration 为向下取整的
    整数秒(与平台回传口径一致:帧数/24 向下取整);ffprobe 缺失时为 None。
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise ValueError(f"仅支持 mp4/mov 视频,收到「{ext or '未知格式'}」")
    if len(content) > _MAX_BYTES:
        raise ValueError(f"视频不得超过 200MB(当前约 {len(content) // 1024 // 1024}MB)")

    try:
        info = _probe(content)
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, KeyError):
        return {"duration": None, "warning": _NO_FFPROBE_WARNING}

    dur = info["duration"]
    if dur < _MIN_SEC or dur > _MAX_SEC:
        raise ValueError(f"视频时长须在 2–30 秒之间(当前 {dur:.1f} 秒)")
    fps = info["fps"]
    if fps and not (_MIN_FPS <= fps <= _MAX_FPS):
        raise ValueError(f"视频帧率须在 24–60 之间(当前 {fps:.0f})")
    height = info["height"]
    if height and height > _MAX_HEIGHT:
        raise ValueError(f"参考视频分辨率最高 720p(当前高度 {height}px)")
    return {"duration": int(dur), "warning": None}
