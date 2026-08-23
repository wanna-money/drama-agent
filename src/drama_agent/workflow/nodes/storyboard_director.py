import uuid
import structlog
from drama_agent.workflow.state import DramaState, ShotDict
from drama_agent.workflow.constants import (
    ShotType, CameraMovement, MAX_SHOT_DURATION, DEFAULT_SHOT_DURATION, SHOT_TYPE_DESC,
)
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

logger = structlog.get_logger()

SYSTEM = """You are a professional film director and storyboard artist.
Break screenplays into individual shots for video production.
Each shot must be filmable as a single continuous clip of 5-10 seconds."""


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


def build_prompt(screenplay: str, analysis: dict) -> tuple[str, str]:
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
{_format_characters(analysis)}

Rules for shots:
- Each shot is at most {MAX_SHOT_DURATION} seconds (for video generation)
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
    "location": "INT. COFFEE SHOP - DAY",
    "description": "Wide establishing shot of a busy city coffee shop in morning light",
    "characters": [],
    "action": "Customers moving through the shop, steam rising from cups",
    "dialogue": ""
  }},
  ...
]"""
    return SYSTEM, user_prompt


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


async def storyboard_director_node(state: DramaState) -> dict:
    system, user_prompt = build_prompt(state["screenplay"], state.get("story_analysis") or {})

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
            "characters": s.get("characters", []),
            "dialogue": s.get("dialogue", ""),
            "action": s.get("action", ""),
            "location": s.get("location", ""),
        }
        shots.append(shot)

    return {
        "shots": shots,
        "current_stage": "storyboard_ready",
    }
