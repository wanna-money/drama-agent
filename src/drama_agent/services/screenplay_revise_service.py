"""剧本对话式改写 · 确认-执行 Agent:单轮结构化决策(ask/apply),不做多步 tool-loop。

规则(见 SYSTEM prompt):意图不明确或用户尚未明确同意改动计划时只回复(ask);
用户已明确同意后才整份改写并输出完整剧本(apply)。apply 却产空一律降级为 ask,
绝不让空剧本被上层写回 checkpointer / 落版本。
"""
from enum import Enum

from drama_agent.services.llm_service import llm_service


class ReviseAction(str, Enum):
    """本轮决策:只回复,还是执行改写。"""

    ASK = "ask"
    APPLY = "apply"


SYSTEM = """你是短剧编剧助手,帮用户逐步改好剧本。规则:
- 先弄清用户想怎么改。若意图不明确、或用户尚未明确同意你的改动计划,则 action="ask":
  reply 里复述你理解的改动计划并请用户确认,不要输出 screenplay。
- 仅当用户已明确同意(如"确认/可以/就这样/改吧")时,才 action="apply":
  screenplay 输出改写后的【完整】剧本(简体中文,保持剧本格式:场景标题/动作/对白),
  reply 给一句简短说明,summary 给一句话概括本次改动(作版本标签)。
- 每次只按已确认的意图改,不擅自加改动。
严格输出 JSON:{"action","reply","screenplay","summary"}。"""

_FALLBACK_ASK_REPLY = "我还没能理解具体的修改方式,能再说说想怎么改吗?"


def build_user_prompt(current_screenplay: str, messages: list[dict]) -> str:
    history = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    return f"""【当前剧本】
{current_screenplay}

【对话历史(含用户本轮发言)】
{history}

请按规则输出 JSON 决策。"""


def _ask(reply: str) -> dict:
    return {
        "action": ReviseAction.ASK.value,
        "reply": reply or _FALLBACK_ASK_REPLY,
        "screenplay": None,
        "summary": None,
    }


async def turn(current_screenplay: str, messages: list[dict], model: str) -> dict:
    user_prompt = build_user_prompt(current_screenplay, messages)
    raw = await llm_service.complete_json(SYSTEM, user_prompt, temperature=0.5, model=model)
    # complete_json 标称 -> dict,但其 _parse_json 遇到顶层是 JSON 数组的模型输出会真返回 list;
    # 归一成 {} 走下方同一条降级为 ask 的路径,而不是在 .get() 上炸成 500。
    if not isinstance(raw, dict):
        raw = {}

    is_apply = raw.get("action") == ReviseAction.APPLY.value
    reply = (raw.get("reply") or "").strip()
    screenplay = (raw.get("screenplay") or "").strip() if is_apply else ""

    # LLM 输出不可信:声称 apply 却给空剧本(或 complete_json 解析失败返回 {})一律降级为 ask。
    if not (is_apply and screenplay):
        return _ask(reply)
    return {
        "action": ReviseAction.APPLY.value,
        "reply": reply or "已按你的要求改好了。",
        "screenplay": screenplay,
        "summary": (raw.get("summary") or "").strip() or None,
    }
