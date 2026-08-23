"""模型下拉数据:从 provider 适配层 registry 派生(不再手维护 settings 列表)。"""
from fastapi import APIRouter

from drama_agent import provider as provider_pkg
from drama_agent.provider.base import Model

router = APIRouter(prefix="/api/config", tags=["config"])


def _llm_dict(m: Model) -> dict:
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {"value": m.id, "label": m.label, "provider": provider.label, "is_default": m.is_default}


def _video_dict(m: Model) -> dict:
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {
        "value": m.id, "label": m.label, "provider": provider.label,
        "resolutions": m.resolutions, "default_resolution": m.default_resolution,
        "is_default": m.is_default,
    }


def _image_dict(m: Model) -> dict:
    # value 用 provider/id 复合 —— image model id 非全局唯一(同一 gpt-image-2 可挂多个 provider),
    # 复合值消歧;resolve_model 支持 "provider/model" 拆分。resolutions/default_resolution 复用视频字段驱动尺寸联动。
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {
        "value": f"{m.provider}/{m.id}", "label": m.label, "provider": provider.label,
        "resolutions": m.resolutions, "default_resolution": m.default_resolution,
        "is_default": m.is_default,
    }


@router.get("/models")
async def list_models(available: bool = False):
    """LLM 模型下拉。available=true 只返回凭证已配 provider 的模型。"""
    reg = provider_pkg.provider_registry
    models = reg.models(kind="llm", available_only=available)
    dm = reg.effective_default("llm")
    return {"models": [_llm_dict(m) for m in models], "default": dm.id if dm else None}


@router.get("/video-models")
async def list_video_models(available: bool = False):
    """视频模型下拉(含 resolutions/default_resolution,驱动前端联动)。"""
    reg = provider_pkg.provider_registry
    models = reg.models(kind="video", available_only=available)
    dm = reg.effective_default("video")
    return {"models": [_video_dict(m) for m in models], "default": dm.id if dm else None}


@router.get("/image-models")
async def list_image_models(available: bool = False):
    """图片模型下拉(供素材生成,含 resolutions/default_resolution 驱动尺寸联动)。
    available=true 只返回凭证已配 + 启用的 provider 的模型。value 为 provider/id 复合(消歧)。"""
    reg = provider_pkg.provider_registry
    models = reg.models(kind="image", available_only=available)
    dm = reg.effective_default("image")
    default = f"{dm.provider}/{dm.id}" if dm else None
    return {"models": [_image_dict(m) for m in models], "default": default}
