"""从剧本/分镜提炼图像 prompt:素材库里没有对应参考图时,不让用户从零描述。

与 prompt_optimize_service 的分工:那边是"把用户已写的粗描述扩写";这里是"用户什么都
没写,从作品内容里把它捞出来"。两者共用 _SUBJECT_BLOCKS(本次任务的锁死项)与
image_prompt_guide(方法),差别只在原料来源。

原料按 subject 分流,且**由后端自己取**(规范 4:前端只给 {subject, key},不搬运原料):
  character  → 剧本正文 + story_analysis 里该角色的 appearance/personality
  background → 该 location 的全部镜头(description/action/光影),因为背景条目本身无描述

提炼失败一律抛,由 API 映射成明确错误 —— 这里不能像 optimize 那样"退回原文",
因为压根没有原文可退。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import structlog

from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service
from drama_agent.services.prompt_optimize_service import _SUBJECT_BLOCKS

logger = structlog.get_logger()

# 提炼支持的素材类。道具/服饰不在内:它们不像人物有 appearance、也不像背景有镜头可依,
# 从剧本里捞"某个道具长什么样"多半是编造 —— 那类仍走用户手写 + optimize。
EXTRACTABLE: frozenset[str] = frozenset({"character", "background"})

# 喂给 LLM 的剧本正文上限。整本小说塞进去既超窗又稀释重点(要找的是一个人的外貌)。
_MAX_SOURCE_CHARS = 6000


class NotExtractable(ValueError):
    """该 subject 不支持提炼(道具/服饰)。与"原料为空"分开:前者是能力边界,后者是数据缺失。"""


class NoMaterial(ValueError):
    """原料不足,提炼会变成编造。宁可显式失败让用户手写,不返回一条凭空捏的描述。"""


def _character_material(
    prose: str, story_analysis: Mapping[str, Any] | None, name: str
) -> str:
    """角色原料 = 已抽出的外貌/性格 + 一段散文。

    prose 是"含这个角色的行文",可能是成稿剧本、故事原文或整本小说 —— 三者对提炼外貌
    等价,故合成一个参数;**不要叫 source_text**,那是 Script 上专指"故事原文"的那一列,
    同名会让人以为这里只收原文而漏掉剧本(调用方的取值顺序见 api/prompt.py)。
    """
    blocks: list[str] = []
    for c in ((story_analysis or {}).get("characters") or []):
        if not isinstance(c, Mapping) or str(c.get("name") or "").strip() != name:
            continue
        for label, field in (("已知外貌", "appearance"), ("性格", "personality")):
            val = str(c.get(field) or "").strip()
            if val:
                blocks.append(f"{label}:{val}")
    text = (prose or "").strip()
    if text:
        blocks.append(f"剧本正文(节选):\n{text[:_MAX_SOURCE_CHARS]}")
    return "\n\n".join(blocks)


def _background_material(shots: Iterable[Mapping[str, Any]] | None, location: str) -> str:
    """背景原料 = 该 location 的全部镜头。

    背景条目只有一个地点名(见 reference_service 模块注释:背景没有实体),描述只能从
    发生在该地点的镜头里聚合。光影字段一并给出:同场景的 lighting/color_temp 已由
    storyboard 收敛成一致,它正是这张背景图该有的基调。
    """
    lines: list[str] = []
    for s in shots or []:
        if not isinstance(s, Mapping) or str(s.get("location") or "").strip() != location:
            continue
        parts = [str(s.get(f) or "").strip() for f in ("description", "action")]
        light = "/".join(
            str(s.get(f) or "").strip() for f in ("lighting", "color_temp") if s.get(f)
        )
        if light:
            parts.append(f"光影:{light}")
        detail = ";".join(p for p in parts if p)
        if detail:
            lines.append(f"- {detail}")
    return "\n".join(lines)


def build_material(
    subject: str, key: str, *,
    prose: str = "", story_analysis: Mapping[str, Any] | None = None,
    shots: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    """按 subject 组装原料。空原料抛 NoMaterial —— 无米之炊只会得到编造的描述。"""
    if subject not in EXTRACTABLE:
        raise NotExtractable(
            f"{subject} 不支持从剧本提炼(仅 {sorted(EXTRACTABLE)});请手写描述后用「优化描述」"
        )
    material = (
        _character_material(prose, story_analysis, key) if subject == "character"
        else _background_material(shots, key)
    )
    if not material.strip():
        raise NoMaterial(
            f"剧本与分镜里找不到关于「{key}」的可用描述,请手写一句再用「优化描述」扩写"
        )
    return material


async def extract_prompt(
    subject: str, key: str, material: str, model: str | None = None,
) -> str:
    """把原料交 LLM 提炼成可直接生成的图像 prompt。

    走 image_prompt_guide(方法)+ 该类锁死项(硬性要求),与 optimize 同源 ——
    两条路径产出的 prompt 要服从同一套规则,否则同一素材类会有两种风格。
    """
    rules = knowledge_store.retrieve("image_prompt_guide")
    rules_block = "\n".join(rules) if rules else (
        "(通用最佳实践:具体可视化、单一主体、明确光影与风格、加约束标签)"
    )
    block = _SUBJECT_BLOCKS.get(subject, "")
    system = (
        "你是图像生成的提示词工程师。用户没有写描述,请**仅依据给定的作品内容**提炼出"
        f"「{key}」的图像 prompt。内容里没提到的特征不要编造,可留白由模型发挥;"
        "只输出 prompt 正文,不要解释、不要加引号。"
    )
    user = f"规则:\n{rules_block}\n\n作品内容:\n{material}\n\n{block}\n\n请输出「{key}」的图像 prompt。"
    from drama_agent.services.prompt_optimize_service import _default_llm_model
    out = await llm_service.complete(system, user, temperature=0.4,
                                     model=model or _default_llm_model())
    text = (out or "").strip()
    if not text:
        raise NoMaterial(f"模型未能从作品内容里提炼出「{key}」的描述,请手写一句")
    return text
