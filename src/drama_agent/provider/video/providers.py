"""内置 video provider 声明。

能力(resolutions/aspect_ratios/supports_seed/supported_actions)在 model 粒度声明,
取代原先散在 config.video_models 列表 + 各 provider 类的 supported_actions。

注意 provider id 与 model id 的区分:
- provider id 带 `-video` 后缀(如 "minimax-video"),避免与同名 LLM provider(如 "minimax")
  在统一 registry 里 id 冲突;
- model id 用无后缀名(如 "minimax"),这才是前端/DB 里 `video_provider` 选择的值;
- provider.protocol 用无后缀名(如 "minimax"),由 video_service 工厂据此实例化实现类。
"""
from __future__ import annotations

from drama_agent.provider.base import Model, Provider

# 内置 video provider 的官方 base_url(锁死,UI 只读)。
SEEDANCE_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"   # 火山方舟 Ark
MINIMAX_VIDEO_BASE_URL = "https://api.minimaxi.com"


def builtin_video_providers() -> list[Provider]:
    return [
        Provider(
            id="seedance-video", label="字节跳动", protocol="seedance",
            base_url=SEEDANCE_BASE_URL,
            models=[
                Model(
                    id="seedance", label="Seedance 2.0",
                    provider="seedance-video", kind="video", is_default=True,
                    resolutions=["720p", "1080p"], default_resolution="1080p",
                    aspect_ratios=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                    default_aspect_ratio="9:16",
                    supported_actions=["rerun", "regenerate"],
                    supports_audio_reference=True, max_reference_audios=3,
                    max_reference_images=9,
                    # 手册:2.0 系列最多 3 个参考视频,总时长 ≤15s
                    max_reference_videos=3,
                    min_duration=4, max_duration=15,
                    supports_seed=True,
                    prompt_guide_key="seedance",
                ),
                Model(
                    id="seedance-2.5", label="Seedance 2.5",
                    provider="seedance-video", kind="video",
                    resolutions=["720p", "1080p"], default_resolution="1080p",
                    aspect_ratios=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
                    default_aspect_ratio="9:16",
                    supported_actions=["rerun", "regenerate"],
                    supports_audio_reference=True, max_reference_audios=10,
                    max_reference_images=30,
                    # 手册:2.5 最多 10 个参考视频,总时长 ≤30s
                    max_reference_videos=10,
                    min_duration=4, max_duration=30,
                    supports_seed=True,
                    # 首帧/首尾帧任务强制 adaptive(平台按首帧图定比例,传具体比例会被拒);
                    # 响应整数秒时间戳(2.0 只响应镜头序号);参考音频可单独输入。
                    forces_adaptive_ratio=True,
                    supports_timestamp_prompt=True,
                    supports_standalone_audio=True,
                    # 只有 2.5 认 omni_reference_task_type;给 2.0 发这个参数是发它不认的字段
                    supports_omni_task_type=True,
                    prompt_guide_key="seedance",
                ),
            ],
        ),
        Provider(
            id="minimax-video", label="MiniMax", protocol="minimax",
            base_url=MINIMAX_VIDEO_BASE_URL,
            models=[
                Model(
                    id="minimax", label="MiniMax H3",
                    provider="minimax-video", kind="video",
                    resolutions=["768P", "2K"], default_resolution="768P",
                    aspect_ratios=["16:9", "9:16", "1:1"],
                    default_aspect_ratio="9:16",
                    supported_actions=["rerun", "regenerate", "upscale"],
                    supports_audio_reference=True, max_reference_audios=3,
                    max_reference_images=9,
                    # H3 v2 没有视频参考:0 让前端的编辑/延长模式自然不渲染
                    max_reference_videos=0,
                    min_duration=4, max_duration=15,
                    # H3 v2 无 seed 字段 → 该模型下「重跑」只能是"再抽一次"
                    supports_seed=False,
                    prompt_guide_key="minimax",
                ),
            ],
        ),
    ]
