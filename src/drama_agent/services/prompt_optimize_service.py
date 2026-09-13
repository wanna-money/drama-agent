"""提示词优化:把粗描述交 LLM 扩写成详细 prompt。规则走知识层(可插拔)。

image → image_prompt_guide(craft md);video → prompt_guide(按目标模型,复用 SP2)。
优化器 LLM 用默认(或传入)LLM;失败/空 → 原样返回。
"""
from __future__ import annotations

import structlog

from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

logger = structlog.get_logger()

# 各素材分类"必须锁死"的要素。缺了它们模型会自由发挥到无法复用:
# 背景里冒出人物 → 场景无法给别的角色复用;道具带手 → 抠不出来也限制构图。
# 与 knowledge/craft/image_prompt_guide.md 的「分类专项」同源:那份是给 LLM 读的方法,
# 这里是**本次任务的硬性追加要求**(逐条落到画面上)。
_SUBJECT_BLOCKS: dict[str, str] = {
    "character": (
        "本次目标是人物角色设定图:请输出一张高精度人物四视图设定板,从左到右依次为"
        "正面全身、侧面全身、背面全身、面部特写;四个视图必须为同一角色,"
        "保持一致的五官/发型/妆容/服装/气质 —— 不同视图之间服装细节(纽扣/腰带/鞋)不得变化;"
        "纯白背景;面部特写清晰展示五官、肌肤纹理、妆容与发丝细节;无文字、无水印、无边框。"
    ),
    "background": (
        "本次目标是场景背景概念图:明确视角、尺度、材质、光源与空间功能,并写清时间与天气"
        "(它决定整场戏的光影基调);画面中**不得出现人物**(背景是给角色站进去的容器,"
        "有人物会让同一场景无法复用);避免不合理透视;无文字、无水印。"
    ),
    "prop": (
        "本次目标是道具参考图:单一主体、居中、纯白背景(需可被单独抠出);写清材质与工艺"
        "及尺度参照;不带关联场景、**不带手部**(手是最易画坏的部位,且会限制后续构图);"
        "无文字、无水印。"
    ),
    "costume": (
        "本次目标是服饰参考图:平铺或立体挂展(明确选一种);写清面料、版型、缝线与配件细节"
        "(造型一致性的依据);**不带人物**(带人物就变成人像图,无法作为服装参考复用);"
        "纯白背景、无文字、无水印。"
    ),
}


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
    # 分类专项要求:四类各有其"锁死项",不只人物需要
    block = _SUBJECT_BLOCKS.get(subject or "") if kind == "image" else None
    extra = f"\n\n{block}" if block else ""
    user = f"规则:\n{rules_block}\n\n用户原始描述:\n{raw}{extra}\n\n请输出优化后的{target} prompt。"
    use_model = model or _default_llm_model()
    try:
        out = await llm_service.complete(system, user, temperature=0.5, model=use_model)
        return (out or "").strip() or raw
    except Exception as e:  # noqa: BLE001 — 优化失败不阻断,退回原文
        logger.warning("prompt optimize failed, returning raw", error=str(e))
        return raw
