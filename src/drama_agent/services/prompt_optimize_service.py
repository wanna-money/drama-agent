"""提示词优化:把粗描述交 LLM 扩写成详细 prompt。规则走知识层(可插拔)。

image → image_prompt_guide(craft md);video → prompt_guide(按目标模型,复用 SP2)。
优化器 LLM 用默认(或传入)LLM;失败/空 → 原样返回。
"""
from __future__ import annotations

import structlog

from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

logger = structlog.get_logger()

_PORTRAIT_FOUR_VIEW = (
    "本次目标是人物角色设定图:请输出一张高精度人物四视图设定板,从左到右依次为"
    "正面全身、侧面全身、背面全身、面部特写;四个视图必须为同一角色,"
    "保持一致的五官/发型/妆容/服装/气质;纯白背景;"
    "面部特写清晰展示五官、肌肤纹理、妆容与发丝细节;无文字、无水印、无边框。"
)


def _rules_for(kind: str, target_model: str | None) -> list[str]:
    if kind == "video":
        if not target_model:
            return []
        try:
            from drama_agent import provider as provider_pkg
            _p, m = provider_pkg.provider_registry.resolve_model(target_model)
            key = m.prompt_guide_key
            return knowledge_store.retrieve("prompt_guide", key=key) if key else []
        except Exception:  # noqa: BLE001 — 解析失败退化为无规则
            return []
    # image(默认)
    return knowledge_store.retrieve("image_prompt_guide")


def _default_llm_model() -> str | None:
    """未指定 model 时的兜底:该 kind 有效默认(is_default → 首个可用)。"""
    try:
        from drama_agent import provider as provider_pkg
        dm = provider_pkg.provider_registry.effective_default("llm")
        return dm.id if dm else None
    except Exception:  # noqa: BLE001 — 兜底失败退化为 None(complete 会报明确错误)
        return None


async def optimize_prompt(
    raw_prompt: str, kind: str = "image", target_model: str | None = None,
    model: str | None = None,
    subject: str | None = None,
) -> str:
    raw = (raw_prompt or "").strip()
    if not raw:
        return raw
    rules = _rules_for(kind, target_model)
    rules_block = (
        "\n".join(rules) if rules
        else "(通用最佳实践:具体可视化、单一主体、明确光影与风格、加约束标签)"
    )
    target = "图像" if kind == "image" else "视频"
    system = (
        f"你是{target}生成的提示词工程师。把用户的粗略描述扩写成一条详细、可直接用于生成的 prompt。"
        "严格遵循给定规则;只输出优化后的 prompt 正文,不要解释、不要加引号。"
    )
    extra = ("\n\n" + _PORTRAIT_FOUR_VIEW) if (kind == "image" and subject == "character") else ""
    user = f"规则:\n{rules_block}\n\n用户原始描述:\n{raw}{extra}\n\n请输出优化后的{target} prompt。"
    use_model = model or _default_llm_model()
    try:
        out = await llm_service.complete(system, user, temperature=0.5, model=use_model)
        return (out or "").strip() or raw
    except Exception as e:  # noqa: BLE001 — 优化失败不阻断,退回原文
        logger.warning("prompt optimize failed, returning raw", error=str(e))
        return raw
