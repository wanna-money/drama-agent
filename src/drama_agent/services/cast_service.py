"""本集阵容(角色名 → Character.id)的解析与确认。角色身份的唯一入口。

为什么需要它:角色管理(Character)与剧本人物(story_analysis.characters)之间若只靠
同名隐式对齐,LLM 每次分析造出的新名字就会与用户手建的角色各自为政。所以:
  · story_analyzer 拿已有角色作硬约束,尽量复用既有名字
  · 名单外的名字**不自动建实体**,交由 cast_review 人工确认(关联到已有 / 新建)
  · 确认结果 = cast:{角色名: character_id},下游一律按 id 取角色,改名不断链

阵容不落独立表:角色身份锚在作品级(Character.project_id),"这一集有谁"由本模块
按剧本抽取结果与作品角色库现场解析即得(规范 4:不为投影再造一份存储)。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog

logger = structlog.get_logger()

# resume 决策里的动作取值(受约束,不用自由字符串)
ACTION_LINK = "link"
ACTION_CREATE = "create"


def analysis_names(story_analysis: Mapping[str, Any] | None) -> list[str]:
    """剧本分析里出场的角色名(去重保序)。characters 与 new_characters 都算 ——
    后者是 LLM 按约束把"名单外的新人物"另放的那一档,同样需要确认身份。
    """
    out: list[str] = []
    seen: set[str] = set()
    src = story_analysis or {}
    for field in ("characters", "new_characters"):
        for c in src.get(field) or []:
            name = str((c.get("name") if isinstance(c, Mapping) else c) or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def appearance_of(story_analysis: Mapping[str, Any] | None, name: str) -> str:
    """该角色在本次分析里的外貌描述(建实体时带上,省得用户重填)。"""
    src = story_analysis or {}
    for field in ("characters", "new_characters"):
        for c in src.get(field) or []:
            if isinstance(c, Mapping) and str(c.get("name") or "").strip() == name:
                return str(c.get("appearance") or "")
    return ""


async def roster_names(project_id: str, state_cast: Mapping[str, str] | None = None) -> list[str]:
    """下游创作节点可用的角色名单。**一个身份只出一个名字**。

    以角色库为准、不只依赖 state["cast"]:cast 由 cast_review 写入状态,而下游节点
    (写剧本/分镜)读到它要跨 interrupt 恢复的状态合并边界,时序上不可靠;角色库是
    作品级的持久权威,任何时刻查都对。

    **别名要折叠**:用户把「程序员」link 到已有角色「角色1」时,cast 是
    {"程序员": <角色1 的 id>} —— 若把 cast 的键与库里的 name 简单取并集,同一身份
    就出两个名字下发给 LLM,它会当成两个人各自分配镜头,而过滤器因两者都"在名单上"
    照样放行(实测:19 镜「程序员」+ 5 镜「角色1」,实为一人)。故 cast 的键只在它
    没有对应到任何库内角色时才补进名单;能对应上的一律用库里的规范名。

    库读不到时退回 state 的键(而非空):空名单会让下游的约束段整体消失。
    """
    cast = {str(k): str(v) for k, v in (state_cast or {}).items() if str(k or "").strip()}
    try:
        from drama_agent.services import character_entity_service as ce
        rows = [r for r in await ce.list_characters(project_id) if r.name]
    except Exception as e:  # noqa: BLE001 — 库读不到就只用 state 的键
        logger.warning("roster lookup failed, falling back to state cast", error=str(e))
        return sorted(cast)
    known_ids = {r.id for r in rows}
    names = {r.name for r in rows}
    # 只补"指向库外(或无 id)"的 cast 键:它们在库里没有规范名可用
    names |= {k for k, cid in cast.items() if cid not in known_ids}
    return sorted(names)


async def roster_by_id(project_id: str) -> dict[str, str]:
    """{character_id: 规范名}。读不到时返回空(调用方据此跳过归一,不阻断)。"""
    try:
        from drama_agent.services import character_entity_service as ce
        return {r.id: r.name for r in await ce.list_characters(project_id) if r.name}
    except Exception as e:  # noqa: BLE001 — 归一是纠偏,读不到就不归一
        logger.warning("roster_by_id failed", error=str(e))
        return {}


def canonical_cast(
    state_cast: Mapping[str, str] | None, roster: Mapping[str, str] | None
) -> dict[str, str]:
    """把 cast 的键换成角色库里的规范名(别名 → 规范名)。

    roster: {character_id: 规范名}。下游按名字查 cast 取 character_id,而分镜里用的是
    规范名 —— 不换键会让规范名查不到 id,该角色的造型/外貌整段丢失。
    """
    out: dict[str, str] = {}
    for name, cid in (state_cast or {}).items():
        out[(roster or {}).get(cid) or name] = cid
    return out


async def resolve(project_id: str, story_analysis: Mapping[str, Any] | None) -> dict:
    """把分析结果对齐到作品角色库。

    返回 {"cast": {名字: character_id}, "pending": [{name, appearance, suggestions}]}:
      cast    —— 已能确定身份的(名字与已有角色完全同名)
      pending —— 需要人工确认的(名单外的新名字)
    角色库读不到时全部视为 pending 会把用户堵在确认步,故此时退回"无待确认"(空 cast),
    让流程继续 —— 阵容缺失只降级为"下游取不到角色图",不阻断出片(规范 6)。
    """
    names = analysis_names(story_analysis)
    if not names:
        return {"cast": {}, "pending": []}
    try:
        from drama_agent.services import character_entity_service as ce
        existing = await ce.list_characters(project_id)
    except Exception as e:  # noqa: BLE001 — 角色库不可读:不堵在确认步
        logger.warning("cast resolve failed, skipping confirmation", error=str(e))
        return {"cast": {}, "pending": []}

    by_name = {r.name: r for r in existing}
    cast: dict[str, str] = {}
    pending: list[dict] = []
    # 候选项对所有 pending 相同(整个作品的角色库),由后端算好下发,前端不自己再拉一次
    suggestions = [{"character_id": r.id, "name": r.name} for r in existing]
    for name in names:
        hit = by_name.get(name)
        if hit is not None:
            cast[name] = hit.id
            continue
        pending.append({
            "name": name,
            "appearance": appearance_of(story_analysis, name),
            "suggestions": suggestions,
        })
    return {"cast": cast, "pending": pending}


async def _backfill_appearance(character_id: str, appearance: str) -> None:
    """给还没有外貌描述的已有角色补上本次分析抽出的外貌。

    已有值**不覆盖**:那可能是用户手写或前几集沉淀下来的,比单次分析更可信。
    没有 appearance 时下游 prompt 只能回落到简略的 description,视频里的角色形象会缩水。
    """
    if not appearance.strip():
        return
    try:
        from drama_agent.services import character_entity_service as ce
        if await ce.get_appearance(character_id):
            return
        await ce.update_character(character_id, appearance=appearance)
    except Exception as e:  # noqa: BLE001 — 补外貌是旁路,失败不阻断确认流程
        logger.warning("appearance backfill failed", character_id=character_id, error=str(e))


async def apply_decisions(
    project_id: str,
    story_analysis: Mapping[str, Any] | None,
    decisions: Mapping[str, Any] | None,
    base_cast: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """把人工确认结果落成 cast。

    decisions: {名字: {"action": "link", "character_id": "..."} | {"action": "create"}}
    未给决策 / 决策不合法的名字按 create 处理 —— 走到这一步说明该角色确实在剧本里出场,
    悄悄丢掉它会让下游永远取不到它的角色图(宁可建一个空壳,身份是可见可改的)。
    """
    from drama_agent.services import character_entity_service as ce
    cast: dict[str, str] = dict(base_cast or {})
    decisions = decisions or {}
    for name in analysis_names(story_analysis):
        if name in cast:
            continue
        d = decisions.get(name) if isinstance(decisions.get(name), Mapping) else {}
        cid = str((d or {}).get("character_id") or "").strip()
        if (d or {}).get("action") == ACTION_LINK and cid:
            cast[name] = cid
            await _backfill_appearance(cid, appearance_of(story_analysis, name))
            continue
        try:
            # appearance 必须走关键字:第三个位置参数是 description(人手写备注),
            # 传错列会让 AI 抽的外貌进不到 get_appearance 读的那一列,下游 prompt 拿不到。
            row = await ce.create_character(
                project_id, name, appearance=appearance_of(story_analysis, name) or None)
            cast[name] = row.id
        except Exception as e:  # noqa: BLE001 — 单个角色建不出来不阻断其余
            logger.warning("cast create failed", name=name, error=str(e))
    return cast
