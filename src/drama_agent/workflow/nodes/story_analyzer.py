import structlog

from drama_agent.workflow.state import DramaState
from drama_agent.services.llm_service import llm_service
from drama_agent.db import session as db_session
from drama_agent.db.enums import Genre
from drama_agent.services import character_service

logger = structlog.get_logger()

_GENRE_VALUES = "/".join(g.value for g in Genre)   # prompt 里的类型清单,随枚举自动同步

SYSTEM = """You are a professional story analyst for short drama productions.
Analyze the given story and extract structured information needed for screenplay adaptation.
Focus on characters (with detailed visual appearance descriptions), setting, plot, and tone.
所有文本字段(title、setting、themes、plot_summary 及每个角色的 appearance、personality)一律用简体中文输出;
仅 genre、tone 使用下方 prompt 给定的英文取值。"""


def build_prompt(raw_input: str, genre: str = Genre.DRAMA.value) -> tuple[str, str]:
    user_prompt = f"""Analyze this story for short drama production:

STORY:
{raw_input}

GENRE: {genre}

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
  ]
}}"""
    return SYSTEM, user_prompt


async def story_analyzer_node(state: DramaState) -> dict:
    system, user_prompt = build_prompt(state["raw_input"], state.get("genre", Genre.DRAMA.value))

    analysis_data = await llm_service.complete_json(system, user_prompt, temperature=0.3, model=state.get("llm_model"))

    # Persist character profiles to PG for later use in prompt generation
    project_id = state["project_id"]
    chars = analysis_data.get("characters", [])
    if chars:
        async with db_session.AsyncSessionLocal() as session:
            for char in chars:
                name = char.get("name", "")
                appearance = char.get("appearance", "")
                if name and appearance:
                    await character_service.save(session, project_id, name, appearance)

    # auto-provision:为抽取的角色建同名 Character 空壳(名字-join);失败不阻断
    try:
        from drama_agent.services import character_entity_service as ce
        existing = {c.name for c in await ce.list_characters(project_id)}
        for char in chars:
            nm = char.get("name", "")
            if nm and nm not in existing:
                await ce.create_character(project_id, nm, char.get("appearance") or None)
                existing.add(nm)
    except Exception as e:  # noqa: BLE001 — 自动建壳失败不阻断出片
        logger.warning("character auto-provision failed", error=str(e))

    return {
        "story_analysis": analysis_data,
        "title": analysis_data.get("title", state.get("title", "Untitled")),
        "current_stage": "story_analyzed",
    }
