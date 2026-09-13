"""文本对话式改写 · 确认-执行 Agent:单轮结构化决策(ask/apply),不做多步 tool-loop。

**一个 agent 服务所有可改写的文本**(故事原文 / 剧本正文 / 剧集里在审的剧本)。
差异只在两处,都由调用方注入,agent 本身对"改的是什么、改完写哪儿"零感知:
  · kind      —— 决定下发哪套创作规则与文体要求(见 _KINDS)
  · 落库出口  —— 调用方拿到 apply 结果后自行决定写哪张表/要不要落版本

规则(见 SYSTEM):意图不明确或用户尚未明确同意改动计划时只回复(ask);用户已明确同意后
才整份改写并输出完整文本(apply)。apply 却产空一律降级为 ask —— 空文本被上层写回会
直接覆盖掉用户原有的内容,那是不可恢复的损失。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service


class ReviseAction(str, Enum):
    """本轮决策:只回复,还是执行改写。"""

    ASK = "ask"
    APPLY = "apply"


class TextKind(str, Enum):
    """可改写的文本类型。受约束取值(规范 1):决定规则来源与文体要求,不能是自由字符串。"""

    STORY = "story"            # 故事原文(用户写的素材,散文体)
    SCREENPLAY = "screenplay"  # 剧本正文(场景标题/动作/对白)


@dataclass(frozen=True)
class _Kind:
    label: str            # 给 LLM 与用户看的名称
    knowledge: str        # 知识层 kind —— 该文体的创作方法论
    form: str             # 文体要求:apply 时输出必须保持的形态


_KINDS: dict[TextKind, _Kind] = {
    TextKind.STORY: _Kind(
        label="故事原文",
        knowledge="story_text_guide",
        form="散文体的故事正文(不要写成剧本格式,不要加场景标题与对白标记)",
    ),
    TextKind.SCREENPLAY: _Kind(
        label="剧本",
        knowledge="screenplay_guide",
        form="剧本格式(场景标题 INT./EXT. / 动作 / 对白)",
    ),
}

_FALLBACK_ASK_REPLY = "我还没能理解具体的修改方式,能再说说想怎么改吗?"


def build_system(kind: TextKind) -> str:
    """按文体拼 system prompt。

    文体要求必须进 prompt:同一个 agent 现在既改散文体的原文也改剧本,不声明的话
    模型会把原文改写成剧本格式(它见过的"短剧"语料多是剧本)。
    """
    k = _KINDS[kind]
    return f"""你是短剧编剧助手,帮用户逐步改好{k.label}。规则:
- 先弄清用户想怎么改。若意图不明确、或用户尚未明确同意你的改动计划,则 action="ask":
  reply 里复述你理解的改动计划并请用户确认,不要输出 text。
- 仅当用户已明确同意(如"确认/可以/就这样/改吧"),或用户的要求本身已经足够明确
  (如"帮我扩写成完整故事""把这段优化得更可拍")时,才 action="apply":
  text 输出改写后的【完整】{k.label}(简体中文,保持{k.form}),
  reply 给一句简短说明,summary 给一句话概括本次改动(作版本标签)。
- 每次只按已确认的意图改,不擅自加改动。
严格输出 JSON:{{"action","reply","text","summary"}}。"""


def build_user_prompt(
    kind: TextKind, current_text: str, messages: list[dict],
    doc_texts: list[str] | None = None,
) -> str:
    """拼 user prompt。创作方法论随文体走 —— 改原文用原文那套(可视化、情绪外化),
    改剧本用剧本那套(格式、场次节奏)。

    doc_texts:用户上传文档抽出的正文。**必须与「当前文本」分块**并注明是参考材料 ——
    混进同一块的话模型会把参考资料当成待改写的对象,直接把用户的剧本换成那份文档。
    """
    k = _KINDS[kind]
    rules = knowledge_store.retrieve(k.knowledge)
    rules_block = f"【创作规则】\n{chr(10).join(rules)}\n\n" if rules else ""
    history = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    body = current_text.strip() or "(还没有内容,请根据用户要求从零撰写)"
    refs = ""
    if doc_texts:
        joined = "\n\n---\n\n".join(doc_texts)
        refs = (f"【用户提供的参考材料(不是待改写的对象,仅作素材)】\n{joined}\n\n")
    return f"""{rules_block}{refs}【当前{k.label}】
{body}

【对话历史(含用户本轮发言)】
{history}

请按规则输出 JSON 决策。"""


def _ask(reply: str) -> dict:
    return {
        "action": ReviseAction.ASK.value,
        "reply": reply or _FALLBACK_ASK_REPLY,
        "text": None,
        "summary": None,
    }


async def turn(
    kind: TextKind, current_text: str, messages: list[dict], model: str,
    doc_texts: list[str] | None = None, images: list[str] | None = None,
) -> dict:
    """跑一轮决策。返回 {action, reply, text, summary};text 仅在 apply 时非空。

    doc_texts / images:用户上传的参考材料(文档抽出的文本 / 图片 data URL)。
    分流已在 attachment_service 完成,此处只负责把它们送进 prompt 与多模态 content。
    """
    system = build_system(kind)
    user_prompt = build_user_prompt(kind, current_text, messages, doc_texts)
    raw = await llm_service.complete_json(
        system, user_prompt, temperature=0.5, model=model, images=images)
    # complete_json 标称 -> dict,但其 _parse_json 遇到顶层是 JSON 数组的模型输出会真返回 list;
    # 归一成 {} 走下方同一条降级为 ask 的路径,而不是在 .get() 上炸成 500。
    if not isinstance(raw, dict):
        raw = {}

    is_apply = raw.get("action") == ReviseAction.APPLY.value
    reply = (raw.get("reply") or "").strip()
    text = (raw.get("text") or "").strip() if is_apply else ""

    # LLM 输出不可信:声称 apply 却给空文本(或 complete_json 解析失败返回 {})一律降级为 ask。
    # 放过去会让上层用空串覆盖用户原有的内容 —— 原文没有版本树,那是不可恢复的损失。
    if not (is_apply and text):
        return _ask(reply)
    return {
        "action": ReviseAction.APPLY.value,
        "reply": reply or "已按你的要求改好了。",
        "text": text,
        "summary": (raw.get("summary") or "").strip() or None,
    }
