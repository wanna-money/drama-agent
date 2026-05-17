import uuid
from drama_agent.workflow.state import DramaState, ShotDict
from drama_agent.services.llm_service import llm_service

SYSTEM = """You are a professional film director and storyboard artist.
Break screenplays into individual shots for video production.
Each shot must be filmable as a single continuous clip of 5-10 seconds."""


async def storyboard_director_node(state: DramaState) -> dict:
    user_prompt = f"""Break this screenplay into individual production shots.

SCREENPLAY:
{state["screenplay"]}

CHARACTER VISUAL REFERENCES:
{_format_characters(state)}

Rules for shots:
- Each shot is 5 or 10 seconds max (for video generation)
- Use shot types: ELS (establishing), LS (full body), MS (waist up), CU (close-up), ECU (extreme close-up)
- Use camera movements: static, pan, tilt, dolly, zoom, tracking
- Include which characters appear in each shot
- Be specific about action and visual content

Return JSON array of shots:
[
  {{
    "scene_number": 1,
    "shot_number": 1,
    "shot_type": "ELS",
    "camera_movement": "static",
    "duration_seconds": 5,
    "location": "INT. COFFEE SHOP - DAY",
    "description": "Wide establishing shot of a busy city coffee shop in morning light",
    "characters": [],
    "action": "Customers moving through the shop, steam rising from cups",
    "dialogue": ""
  }},
  ...
]"""

    shots_data = await llm_service.complete_json(SYSTEM, user_prompt, temperature=0.3, model=state.get("llm_model"))

    if isinstance(shots_data, dict) and "shots" in shots_data:
        shots_data = shots_data["shots"]

    if not isinstance(shots_data, list):
        shots_data = []

    shots: list[ShotDict] = []
    for s in shots_data:
        shot: ShotDict = {
            "shot_id": str(uuid.uuid4()),
            "scene_number": s.get("scene_number", 1),
            "shot_number": s.get("shot_number", 1),
            "shot_type": s.get("shot_type", "MS"),
            "camera_movement": s.get("camera_movement", "static"),
            "duration_seconds": min(int(s.get("duration_seconds", 5)), 10),
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


def _format_characters(state: DramaState) -> str:
    if not state.get("story_analysis"):
        return ""
    chars = state["story_analysis"].get("characters", [])
    return "\n".join(
        f"- {c['name']}: {c['appearance']}"
        for c in chars
        if c.get("name") and c.get("appearance")
    )
