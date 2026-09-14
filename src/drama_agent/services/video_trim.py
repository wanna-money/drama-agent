"""生成后按叙事真实时长裁剪本地视频文件。

用途见 workflow/state.py 的 ShotDict.narrative_duration_seconds 字段注释:视频平台
有单支生成下限(如 4s),而一次击中/爆炸这类动作的真实时长可能明显更短——平台仍按
下限生成,多出的尾段是模型为填满时长而拉长/放慢/静止的填充,这正是成片"像 PPT
一样卡顿"的直接成因之一。裁剪把这段填充切掉,让镜头的实际长度匹配真实节奏。

**未装 ffmpeg 时跳过裁剪、原样保留下载到的文件**——理由与 video_validate.py 一致:
裁剪失败不该让整支已经生成成功的视频报废,这是锦上添花的后处理,不是生成的必要步骤。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def trim_to_narrative_duration(video_path: Path, narrative_duration_seconds: int) -> None:
    """就地把 video_path 裁到前 narrative_duration_seconds 秒(原地覆盖)。

    用 `-c copy` 走关键帧对齐裁剪而非重编码:重编码更精确但慢得多、且要吃一遍画质,
    对"切掉一段填充尾巴"这种粗粒度需求没必要——裁剪点落在关键帧上的一两帧误差,
    比整支视频重新编码的耗时代价小得多。

    裁到临时文件再原子替换(与 storage_service.download_file 同一模式):裁剪中途
    失败不能让 video_path 变成损坏文件——那会让一支已经生成成功的视频报废。
    """
    tmp_path = video_path.with_name(f".{video_path.name}.trimmed.part")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-t", str(narrative_duration_seconds),
        "-c", "copy",
        # 显式指定容器格式:输出文件名带 .part 后缀,ffmpeg 无法从扩展名推断该用哪个
        # muxer(实测报 "Unable to choose an output format"),必须明说,不能依赖文件名嗅探。
        "-f", "mp4",
        str(tmp_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning(
            "trim_to_narrative_duration: ffmpeg 未安装,跳过裁剪,保留原始时长",
            extra={"video_path": str(video_path)},
        )
        return
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        # 裁剪失败不阻断出片(规范 6):原视频仍然可用,只是多出的尾段没被切掉。
        logger.warning(
            "trim_to_narrative_duration: ffmpeg 裁剪失败,保留原始时长",
            extra={"video_path": str(video_path), "stderr": stderr.decode(errors="replace")},
        )
        tmp_path.unlink(missing_ok=True)
        return
    tmp_path.replace(video_path)
