"""素材 AI 生成/编辑:把图片模型解析成 provider 的 protocol → 产原始 bytes。

与 asset_service(纯元数据+存储)分离:本模块需要 registry + image protocol。
不直接开 session;读素材字节委托 asset_service.read_asset_bytes。
"""
from __future__ import annotations

from drama_agent.provider.image.protocols import get_image_protocol
from drama_agent.services import usage_service
from drama_agent.workflow.constants import VISUAL_STYLE_PHRASE


async def generate_image(
    model_id: str, prompt: str, *, size: str | None = None, n: int = 1,
    visual_style: str = "",
) -> list[bytes]:
    """visual_style 非空时把风格短语拼进 prompt 末尾——仅调用方传了才拼(全局素材库场景
    不传,保持风格无关的现状不变);调用方决定要不要传,本函数不判断"这是不是全局调用"。
    """
    from drama_agent import provider as provider_pkg
    provider, model = provider_pkg.provider_registry.resolve_model(model_id)  # ValueError 未知 model
    proto = get_image_protocol(provider.protocol)                            # ValueError 未知 protocol
    style_phrase = VISUAL_STYLE_PHRASE.get(visual_style, "")
    final_prompt = f"{prompt}。整体视觉风格:{style_phrase}。" if style_phrase else prompt
    result = await proto.generate(provider, model, final_prompt, size=size, n=n)  # NotImplementedError 可能
    await usage_service.record_image(
        getattr(result, "usage", None) or {}, provider=provider.id, model=model.id
    )
    return result.images


async def edit_image(
    asset_id: str, model_id: str, prompt: str, *, size: str | None = None, n: int = 1
) -> list[bytes]:
    from drama_agent import provider as provider_pkg
    from drama_agent.services import asset_service
    image = await asset_service.read_asset_bytes(asset_id)
    if image is None:
        raise LookupError(f"asset not found: {asset_id}")
    provider, model = provider_pkg.provider_registry.resolve_model(model_id)
    proto = get_image_protocol(provider.protocol)
    result = await proto.edit(provider, model, image, prompt, mask=None, size=size, n=n)
    return result.images
