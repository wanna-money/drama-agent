"""已确认阵容对下游创作节点的硬约束(prompt 片段的唯一来源)。

为什么下游也要约束:cast 在写剧本**之前**就定好了,但写剧本/分镜这两步本身也会发明
人物("女人""顾客"),它们没有 character_id → 拿不到造型与外貌 → 在视频里的形象每个镜头
都不一样。故有台词/有形象的角色必须落在名单内。

真正的群演(路过的人、背景里的顾客)不该为此建角色档案,所以给 LLM 留一条出路:
不给他们起名字,在动作描述里以「一名顾客」这类无名方式出现,不进 characters 字段。

约束文案只在此处维护 —— 各节点手抄一份会漂移(四个节点只有两个抄到过输出语言规则,
就是这么来的)。
"""
from __future__ import annotations

UNNAMED_EXTRA_HINT = (
    "真正的群演/路人不要起名字:在动作描述里写成「一名顾客」「路过的行人」这类无名角色,"
    "**不要**把他们放进 characters 字段。"
)


def cast_constraint_block(cast_names: list[str] | None) -> str:
    """已确认阵容 → prompt 里的硬约束段。名单为空则返回空串(无约束可下发)。"""
    names = [n for n in (cast_names or []) if str(n or "").strip()]
    if not names:
        return ""
    listed = "、".join(names)
    return f"""

CONFIRMED CAST(本集已确认的角色,**只能**用这些名字):
{listed}

角色命名硬约束:
- 有台词或有形象刻画的角色,名字**只能**取自上面这份名单(不要改写称呼、不要用别名)。
- 不得发明名单之外的具名角色 —— 名单外的人物拿不到造型与外貌设定,形象无法保持一致。
- {UNNAMED_EXTRA_HINT}"""
