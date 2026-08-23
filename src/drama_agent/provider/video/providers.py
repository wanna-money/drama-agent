"""内置 video provider 声明。

能力(resolutions/default_resolution/supported_actions)在 model 粒度声明,
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
                    supported_actions=["rerun", "regenerate"],
                    supports_audio_reference=True, max_reference_audios=3,
                    prompt_guide_key="seedance",
                ),
                Model(
                    id="seedance-2.5", label="Seedance 2.5",
                    provider="seedance-video", kind="video",
                    resolutions=["720p", "1080p"], default_resolution="1080p",
                    supported_actions=["rerun", "regenerate"],
                    supports_audio_reference=True, max_reference_audios=10,
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
                    supported_actions=["rerun", "regenerate", "upscale"],
                    supports_audio_reference=True, max_reference_audios=3,
                    prompt_guide_key="minimax",
                ),
            ],
        ),
    ]
