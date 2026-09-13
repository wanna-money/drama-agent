"""模型下拉数据:从 provider 适配层 registry 派生(不再手维护 settings 列表)。"""
from fastapi import APIRouter

from drama_agent import provider as provider_pkg
from drama_agent.provider.base import Model

router = APIRouter(prefix="/api/config", tags=["config"])


def _llm_dict(m: Model) -> dict:
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {
        "value": m.id, "label": m.label, "provider": provider.label, "is_default": m.is_default,
        # 该模型所属 provider 的凭证配没配。**不下发 key 本身**,只回结论 ——
        # 界面据此把未配凭证的模型标为不可选并提示去哪配置。
        "credential_configured": provider.resolve_credential() is not None,
    }


def _video_dict(m: Model) -> dict:
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {
        # value 只是"选了哪个模型"的标识;真正开拍要用的两样分开下发:
        #   provider_id —— **protocol**,即该 provider 用哪个实现
        #                  (video_service.get_provider 认的就是这套词表)
        #   model_id    —— 该 provider 下的模型
        #
        # 为什么是 protocol 而不是 provider.id:Provider.protocol 的定义就是
        # "→ Protocol 实现 key",而 id 是这条声明的名字(seedance-video / cloud 都可以
        # 用同一个 seedance 实现)。早先只发 value=m.id + provider=展示名,两个都不是
        # 实现 key —— 于是前端只能把 model id 填进 video_provider,开拍时报
        # "Unknown video provider: Doubao-Seedance-2.0-fast";换成发 id 也一样错
        # (会报 "Unknown video provider: seedance-video",有测试守着这一点)。
        "value": m.id, "label": m.label, "provider": provider.label,
        "provider_id": provider.protocol, "model_id": m.id,
        "resolutions": m.resolutions, "default_resolution": m.default_resolution,
        # 比例选项与默认值由后端下发(权威在 provider 声明);前端不自带一份写死的列表
        "aspect_ratios": m.aspect_ratios, "default_aspect_ratio": m.default_aspect_ratio,
        # 该模型能否复现同一支视频 —— 前端据此提示"重跑"的语义,不在前端另判一次
        "supports_seed": m.supports_seed,
        # 参考图上限:简单模式让用户手动传图,前端据此拦住超限提交,不自算
        "max_reference_images": m.max_reference_images,
        "max_reference_audios": m.max_reference_audios,
        "supports_audio_reference": m.supports_audio_reference,
        # 参考视频上限:0 表示该模型没有视频参考,前端据此不渲染编辑/延长模式
        "max_reference_videos": m.max_reference_videos,
        "supports_omni_task_type": m.supports_omni_task_type,
        # 单支时长的合法区间(直接生成模式用);前端不自带写死的清单。
        # 是区间而非档位 —— 平台按区间收(见 provider/base.Model)
        "min_duration": m.min_duration,
        "max_duration": m.max_duration,
        # 构造约束:界面据此提示能力(如"该模型的比例由首帧图决定"),不在前端另判一次
        "forces_adaptive_ratio": m.forces_adaptive_ratio,
        "supports_timestamp_prompt": m.supports_timestamp_prompt,
        "supports_standalone_audio": m.supports_standalone_audio,
        "is_default": m.is_default,
        # 该模型所属 provider 的凭证配没配。**不下发 key 本身**,只回结论 ——
        # 界面据此把未配凭证的模型标为不可选并提示去哪配置。
        # 不配就选中的话,SDK 会以空 key 发请求并报 "Connection error.",
        # 那条错误与"没配 key"毫无关联,且要等整条流水线跑完才看到。
        "credential_configured": provider.resolve_credential() is not None,
    }


def _image_dict(m: Model) -> dict:
    # value 用 provider/id 复合 —— image model id 非全局唯一(同一 gpt-image-2 可挂多个 provider),
    # 复合值消歧;resolve_model 支持 "provider/model" 拆分。resolutions/default_resolution 复用视频字段驱动尺寸联动。
    provider = provider_pkg.provider_registry.get_provider(m.provider)
    return {
        "value": f"{m.provider}/{m.id}", "label": m.label, "provider": provider.label,
        "resolutions": m.resolutions, "default_resolution": m.default_resolution,
        "is_default": m.is_default,
        # 与 video 同理:凭证状态的权威在后端,只回结论。
        "credential_configured": provider.resolve_credential() is not None,
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


@router.get("/storage")
async def storage_status():
    """公网存储是否可用。

    只回结论、**不回任何凭证**。前端据此启用/禁用「视频编辑/延长」——
    规则的权威在后端(规范 4),前端不去猜"配了没有"。
    """
    from drama_agent.services.public_storage import public_storage_available

    return {"available": public_storage_available()}
