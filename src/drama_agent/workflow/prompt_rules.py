"""跨节点统一的 LLM 输出规则的单一真相(目前:输出语言)。

节点各自的 SYSTEM 只写"你是谁、做什么";"用什么语言输出"这类所有节点一致的契约
收敛在此,由 `system_prompt()` 统一拼接。

为什么要收敛:这条规则原本靠各节点手抄一句中文 —— 4 个 LLM 节点只有 story_analyzer
与 screenplay_writer 抄到了,storyboard_director / prompt_engineer / 剧本修改节点全漏,
于是分镜与视频 prompt 长期输出英文。改成共享常量后,加节点自动继承,不会再漏。
"""
from __future__ import annotations

OUTPUT_LANGUAGE_RULE = """输出语言(强制):所有自然语言字段一律用简体中文,
包括描述、动作、台词、地点、梗概、正向与负向提示词。即便上文的指令、模板、
参考资料是英文,输出仍必须是中文——不要跟随输入语言。
例外只有两类:① 由 prompt 明确给定英文取值的枚举字段(如 shot_type、camera_movement、
genre、tone)保持英文原样;② 专有名词、品牌名、无通行中译的技术术语可保留原文。"""


def system_prompt(role: str, *extra: str) -> str:
    """拼出完整 system prompt:节点角色描述 + 节点特有补充 + 全局输出规则。

    extra 只放"本节点独有"的约束;凡是所有节点都该守的,加到 OUTPUT_LANGUAGE_RULE
    这类共享常量里,别在各节点重复。空白的 extra 自动跳过。
    """
    parts = [role.strip(), *(e.strip() for e in extra if e and e.strip()), OUTPUT_LANGUAGE_RULE]
    return "\n\n".join(parts)
