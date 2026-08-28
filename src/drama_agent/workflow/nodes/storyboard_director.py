import uuid
from typing import cast
import structlog
from drama_agent.workflow.state import DramaState, ShotDict
from drama_agent.workflow.constants import (
    ShotType, CameraMovement, MAX_SHOT_DURATION, MIN_SHOT_DURATION,
    DEFAULT_SHOT_DURATION, SHOT_TYPE_DESC,
)
from drama_agent.config import settings
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.cast_constraint import cast_constraint_block
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

SYSTEM = system_prompt("""You are a professional film director and storyboard artist.
Break screenplays into individual shots for video production.
Each shot must be filmable as a single continuous clip of 5-10 seconds.""")


def _format_characters(analysis: dict) -> str:
    chars = (analysis or {}).get("characters", [])
    return "\n".join(
        f"- {c['name']}: {c['appearance']}"
        for c in chars
        if c.get("name") and c.get("appearance")
    )


def _shot_types_line() -> str:
    return ", ".join(f"{t.value} ({SHOT_TYPE_DESC[t.value]})" for t in ShotType)


def _camera_moves_line() -> str:
    return ", ".join(c.value for c in CameraMovement)


def build_prompt(
    screenplay: str, analysis: dict, target_seconds: int | None = None,
    notes: str | None = None, cast_names: list[str] | None = None,
) -> tuple[str, str]:
    """target_seconds:全片目标时长(秒),约束镜头总时长;缺省取 config 的 target_episode_seconds。
    notes:分镜被打回重做时的人工意见,拼进 prompt 尾部引导重生成(仿 prompt_engineer)。

    cast_names:已确认阵容,作为 shots[].characters 的**受约束取值**下发。名单外的名字
    进了 characters,下游按 character_id 取造型与外貌就会落空(该角色形象逐镜漂移)。
    """
    target_seconds = target_seconds or settings.target_episode_seconds
    guides = knowledge_store.retrieve("storyboard_guide")
    guide_block = "\n".join(f"- {g}" for g in guides)

    shot_lang = "\n\n".join(knowledge_store.retrieve("shot_language"))
    visual = "\n\n".join(knowledge_store.retrieve("visual_aesthetics"))
    methodology_block = ""
    if shot_lang:
        methodology_block += f"\n\nShot-language methodology:\n{shot_lang}"
    if visual:
        methodology_block += f"\n\nVisual-aesthetics methodology:\n{visual}"

    user_prompt = f"""Break this screenplay into individual production shots.

SCREENPLAY:
{screenplay}

CHARACTER VISUAL REFERENCES:
{_format_characters(analysis)}{cast_constraint_block(cast_names)}

Rules for shots:
- shots[].characters 里只填已确认阵容里的名字;无名群演不进该字段(写在 action 里)
- Each shot is at most {MAX_SHOT_DURATION} seconds (for video generation)
- 全片目标时长约 {target_seconds} 秒:所有镜头 duration_seconds 之和应接近该值
  (约 {max(1, target_seconds // DEFAULT_SHOT_DURATION)} 个镜头上下),不要大幅超出
- Use shot types: {_shot_types_line()}
- Use camera movements: {_camera_moves_line()}

Craft guidelines:
{guide_block}{methodology_block}

Return JSON array of shots:
[
  {{
    "scene_number": 1,
    "shot_number": 1,
    "shot_type": "{ShotType.ELS.value}",
    "camera_movement": "{CameraMovement.STATIC.value}",
    "duration_seconds": {DEFAULT_SHOT_DURATION},
    "location": "内景 咖啡馆 - 日",
    "description": "晨光里熙熙攘攘的城市咖啡馆,大远景建立环境",
    "characters": [],
    "action": "客人穿行于店内,杯口热气升腾",
    "dialogue": ""
  }},
  ...
]"""
    if notes:
        user_prompt += f"\n\nRevision notes (address these when regenerating the shots):\n{notes}"
    return SYSTEM, user_prompt


def _filter_cast(names, cast_names: list[str], shot_idx: int) -> list[str]:
    """把 characters 卡回已确认阵容,名单外的丢弃并记 warning(可观测,不静默)。

    prompt 约束只是软的,LLM 仍会发明人物。名单外的名字留在 characters 里,下游按
    character_id 取造型/外貌必然落空 → 该角色在每个镜头里长相都不同。丢弃后它退化为
    "无名群演"(仍在 action 描述里),形象由文本引导,这是可接受的降级;留着则是失控。

    cast_names 为空(未经确认流程,如复用剧本直达分镜)时不过滤 —— 那时没有名单可依据。
    """
    if not isinstance(names, list):
        return []
    if not cast_names:
        return [str(n) for n in names if str(n or "").strip()]
    allowed = set(cast_names)
    kept: list[str] = []
    dropped: list[str] = []
    for n in names:
        name = str(n or "").strip()
        if not name:
            continue
        (kept if name in allowed else dropped).append(name)
    if dropped:
        logger.warning(
            "storyboard: dropped off-roster characters from shot",
            shot_index=shot_idx, dropped=dropped, roster=sorted(allowed),
        )
    return kept


def _coerce_enum(value, enum_cls, default, field: str, shot_idx: int):
    """把模型给的值卡回枚举;越界则 fallback 到默认并记 warning(可观测,不静默)。"""
    valid = {m.value for m in enum_cls}
    if value in valid:
        return value
    logger.warning(
        "storyboard: invalid enum value from model, using default",
        field=field, got=value, default=default, shot_index=shot_idx,
    )
    return default


def _converge_duration(shots: list[dict], target_seconds: int) -> tuple[list[dict], bool]:
    """总时长收敛:超目标按比例压缩到 [MIN,MAX] 秒,镜头一个不少。

    返回 (收敛后的镜头, 是否仍超目标)。压到下限仍超 = 镜头数过多,这是 LLM 的产出
    问题,交给用户决策(duration_over_target),代码不擅自砍镜头 —— 砍镜头 = 代码替用户
    做剪辑决策。总时长已在目标内则原样返回(收敛是纠偏,不无条件重排)。
    """
    total = sum(int(s.get("duration_seconds") or 0) for s in shots)
    if total <= target_seconds:
        return shots, False
    scale = target_seconds / total
    out = [
        {**s, "duration_seconds": max(
            MIN_SHOT_DURATION,
            min(MAX_SHOT_DURATION, round(int(s.get("duration_seconds") or 0) * scale)))}
        for s in shots
    ]
    new_total = sum(int(s["duration_seconds"]) for s in out)
    return out, new_total > target_seconds


async def storyboard_director_node(state: DramaState, target_seconds: int | None = None) -> dict:
    # 目标时长优先级:显式传参 > 集级 state["target_seconds"] > config 默认。
    # 生产中图按 (state) 单参调用,故靠 state 携带集级目标(见 runner._build_initial_state)。
    from drama_agent.services import cast_service
    target_seconds = target_seconds or state.get("target_seconds") or settings.target_episode_seconds
    cast_names = await cast_service.roster_names(state["project_id"], state.get("cast"))
    system, user_prompt = build_prompt(
        state["screenplay"], state.get("story_analysis") or {},
        target_seconds, notes=state.get("storyboard_revision_notes") or None,
        cast_names=cast_names,
    )

    shots_data = await llm_service.complete_json(system, user_prompt, temperature=0.3, model=state.get("llm_model"))

    if isinstance(shots_data, dict) and "shots" in shots_data:
        shots_data = shots_data["shots"]

    if not isinstance(shots_data, list):
        shots_data = []

    shots: list[ShotDict] = []
    for idx, s in enumerate(shots_data):
        shot: ShotDict = {
            "shot_id": str(uuid.uuid4()),
            "scene_number": s.get("scene_number", 1),
            "shot_number": s.get("shot_number", 1),
            "shot_type": _coerce_enum(
                s.get("shot_type"), ShotType, ShotType.MS.value, "shot_type", idx),
            "camera_movement": _coerce_enum(
                s.get("camera_movement"), CameraMovement, CameraMovement.STATIC.value,
                "camera_movement", idx),
            "duration_seconds": min(int(s.get("duration_seconds", DEFAULT_SHOT_DURATION)), MAX_SHOT_DURATION),
            "description": s.get("description", ""),
            "characters": _filter_cast(s.get("characters", []), cast_names, idx),
            "dialogue": s.get("dialogue", ""),
            "action": s.get("action", ""),
            "location": s.get("location", ""),
        }
        shots.append(shot)

    # 总时长收敛:超目标按比例压缩,镜头一个不少;压到下限仍超只标记不阻断(交审核决策)。
    # cast:list[ShotDict] 是 list[dict] 的安全放宽(收敛只读 duration_seconds),mypy 因不变性不自动放宽。
    converged, over = _converge_duration(cast(list[dict], shots), target_seconds)
    if over:
        logger.warning(
            "storyboard: total duration over target even at per-shot floor",
            target=target_seconds,
            total=sum(int(s["duration_seconds"]) for s in converged),
            shots=len(converged),
        )
    return {
        "shots": converged,
        "duration_over_target": over,
        "current_stage": "storyboard_ready",
    }
