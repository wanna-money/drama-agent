"""内置 image provider 声明(种子)。

- 豆包 Seedream(火山方舟 Ark,启用):复用 seedance 同款 ark_api_key。
- gpt-image-2(预留,enabled=False):国内不可达,前端显示禁用态;用户配 OpenAI key 并启用后可用。
model id 为占位,用户可在模型管理界面改为其实际 endpoint/model 名。
"""
from __future__ import annotations

from drama_agent.config import settings
from drama_agent.provider.base import Model, Provider

# 内置 image provider 的官方 base_url(锁死,UI 只读)。
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"   # 火山方舟 Ark
OPENAI_BASE_URL = "https://api.openai.com/v1"


def builtin_image_providers() -> list[Provider]:
    return [
        Provider(
            id="doubao-image", label="豆包 Seedream", protocol="doubao-image",
            base_url=ARK_BASE_URL,
            api_key=settings.ark_api_key or None, enabled=True,
            models=[
                Model(id="doubao-seedream-3-0-t2i", label="Seedream 5.0 pro",
                      provider="doubao-image", kind="image",
                      resolutions=["1024x1024", "864x1152", "1152x864", "1280x720", "720x1280"],
                      default_resolution="1024x1024"),
            ],
        ),
        Provider(
            id="openai-image", label="OpenAI GPT Image", protocol="openai-image",
            base_url=OPENAI_BASE_URL,
            api_key=settings.openai_api_key or None, enabled=False,
            models=[
                Model(id="gpt-image-2", label="GPT Image 2",
                      provider="openai-image", kind="image",
                      resolutions=["1024x1024", "1536x1024", "1024x1536"],
                      default_resolution="1024x1024"),
            ],
        ),
    ]
