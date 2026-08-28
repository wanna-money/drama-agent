import structlog

from drama_agent.workflow.state import DramaState
from drama_agent.services.llm_service import llm_service
from drama_agent.db.enums import Genre
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

_GENRE_VALUES = "/".join(g.value for g in Genre)   # prompt 里的类型清单,随枚举自动同步

SYSTEM = system_prompt(
    """You are a professional story analyst for short drama productions.
Analyze the given story and extract structured information needed for screenplay adaptation.
Focus on characters (with detailed visual appearance descriptions), setting, plot, and tone.""",
    "本节点的 genre、tone 必须取下方 prompt 给定的英文取值(它们是枚举,不翻译)。",
)


def build_prompt(
    raw_input: str, genre: str = Genre.DRAMA.value,
    known_characters: list[dict] | None = None,
) -> tuple[str, str]:
    """known_characters:本作品已有角色(name/appearance)。非空时作为**受约束取值**下发 ——
    同一作品的角色身份是既定事实,不该由每次分析重新发明名字(那正是"角色管理与剧本
    人物对不上"的根源)。与 _GENRE_VALUES 把枚举拼进 prompt 是同一手法。
    """
    roster = ""
    if known_characters:
        listed = "\n".join(
            f"- {c['name']}: {c.get('appearance') or c.get('description') or ''}"
            for c in known_characters if c.get("name")
        )
        roster = f"""

EXISTING CAST (本作品已确立的角色,**必须**优先复用):
{listed}

角色命名硬约束:
- `characters` 里的 name **只能**取自上面这份名单(同一个人不要改写称呼、不要用别名)。
- 剧情确实需要名单之外的新人物时,把它们放进单独的 `new_characters` 字段,不要混进 `characters`。"""

    user_prompt = f"""Analyze this story for short drama production:

STORY:
{raw_input}

GENRE: {genre}{roster}

Return JSON with this exact structure:
{{
  "title": "story title",
  "genre": "{_GENRE_VALUES}",
  "setting": "time and place description",
  "themes": ["theme1", "theme2"],
  "tone": "serious/lighthearted/tense/romantic",
  "scene_count_estimate": 5,
  "plot_summary": "2-3 sentence plot summary",
  "characters": [
    {{
      "name": "Character Name",
      "appearance": "Detailed visual description: hair color, length, style; skin tone; eye color; height/build; typical clothing style and colors. Be specific enough for video generation.",
      "personality": "key personality traits",
      "reference_image_url": null
    }}
  ],
  "new_characters": []
}}"""
    return SYSTEM, user_prompt


async def _known_characters(project_id: str) -> list[dict]:
    """本作品已有角色(阵容)。读不到时返回空 —— 无约束地分析仍能出片,不因此阻断。"""
    try:
        from drama_agent.services import character_entity_service as ce
        rows = await ce.list_characters(project_id)
    except Exception as e:  # noqa: BLE001 — 取不到阵容就退回无约束分析
        logger.warning("known cast lookup failed", error=str(e))
        return []
    return [
        {"name": r.name, "appearance": getattr(r, "appearance", None), "description": r.description}
        for r in rows
    ]


async def story_analyzer_node(state: DramaState) -> dict:
    project_id = state["project_id"]
    # 已有角色作为硬约束下发。**不得在此建角色实体**:身份要由 cast_review 人工确认后
    # 才落库,否则 LLM 造的名字会直接变成实体,与用户手建的角色各自为政。
    known = await _known_characters(project_id)
    system, user_prompt = build_prompt(
        state["raw_input"], state.get("genre", Genre.DRAMA.value), known)

    analysis_data = await llm_service.complete_json(system, user_prompt, temperature=0.3, model=state.get("llm_model"))

    return {
        "story_analysis": analysis_data,
        "title": analysis_data.get("title", state.get("title", "Untitled")),
        "current_stage": "story_analyzed",
    }
