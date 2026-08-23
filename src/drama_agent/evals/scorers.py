"""节点输出评分函数：规则型（本地、确定）+ LLM-judge 占位。"""
from drama_agent.workflow.constants import ShotType

Score = dict  # {"name": str, "passed": bool, "score": float, "detail": str}

_VALID_SHOT_TYPES = {t.value for t in ShotType}


def _s(name: str, passed: bool, detail: str = "") -> Score:
    return {"name": name, "passed": passed, "score": 1.0 if passed else 0.0, "detail": detail}


def score_story_analysis(raw_output: str, parsed: dict) -> list[Score]:
    chars = parsed.get("characters") or []
    return [
        _s("has_setting", bool(parsed.get("setting"))),
        _s("has_themes", bool(parsed.get("themes"))),
        _s("has_characters", len(chars) > 0),
        _s("characters_have_appearance",
           bool(chars) and all(c.get("appearance") for c in chars),
           "每个角色需有 appearance"),
    ]


def score_screenplay(raw_output: str) -> list[Score]:
    text = raw_output or ""
    return [
        _s("non_empty", len(text.strip()) > 0),
        _s("has_scene_markers", ("INT." in text or "EXT." in text), "需含 INT./EXT. 场景标记"),
    ]


def score_storyboard(raw_output: str, parsed: list) -> list[Score]:
    is_list = isinstance(parsed, list) and len(parsed) > 0
    durations_ok = is_list and all(int(s.get("duration_seconds", 99)) <= 10 for s in parsed)
    types_ok = is_list and all(s.get("shot_type") in _VALID_SHOT_TYPES for s in parsed)
    return [
        _s("is_non_empty_list", is_list),
        _s("durations_within_10s", bool(durations_ok)),
        _s("valid_shot_types", bool(types_ok)),
    ]


def score_prompt(raw_output: str, parsed: dict) -> list[Score]:
    return [
        _s("has_prompt_text", bool(parsed.get("prompt_text"))),
        _s("has_negative_prompt", bool(parsed.get("negative_prompt"))),
    ]


async def llm_judge(criteria: str, output: str, model: str | None = None) -> Score:
    """LLM-as-judge 占位：第一版不接真评审，返回 skipped。后续可接 llm_service。"""
    return {"name": "llm_judge", "passed": True, "score": 0.0, "detail": "skipped (not implemented)"}
