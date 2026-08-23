from drama_agent.workflow.state import DramaState
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

SYSTEM = """You are a professional screenplay writer specializing in short dramas.
Write screenplays in standard format with scene headings, action lines, and dialogue.
Each scene should be self-contained and visually compelling.
用简体中文创作整个剧本:场景标题、动作描述、对白全部用中文(专有名词 / 品牌名可保留原文)。"""


def build_prompt(analysis: dict) -> tuple[str, str]:
    char_list = "\n".join(
        f"- {c.get('name', 'Unknown')}: {c.get('appearance', '')} | {c.get('personality', '')}"
        for c in analysis.get("characters", [])
        if c.get("name")
    )

    # 软知识(如何写好)来自 knowledge;硬性格式要求留在下方 prompt。
    guides = knowledge_store.retrieve("screenplay_guide")
    guide_block = "\n".join(f"- {g}" for g in guides)

    methodology = "\n\n".join(knowledge_store.retrieve("story_structure"))
    methodology_block = f"\n\nStory-structure methodology:\n{methodology}" if methodology else ""

    user_prompt = f"""Write a complete short drama screenplay based on this analysis:

TITLE: {analysis.get("title")}
GENRE: {analysis.get("genre")}
SETTING: {analysis.get("setting")}
TONE: {analysis.get("tone")}
THEMES: {", ".join(analysis.get("themes", []))}
PLOT: {analysis.get("plot_summary")}

CHARACTERS:
{char_list}

Format requirements:
- Use standard screenplay format (INT./EXT. LOCATION - DAY/NIGHT)
- Aim for {analysis.get("scene_count_estimate", 5)} scenes total

Craft guidelines:
{guide_block}{methodology_block}

Write the complete screenplay now:"""
    return SYSTEM, user_prompt


async def screenplay_writer_node(state: DramaState) -> dict:
    analysis = state["story_analysis"]
    system, user_prompt = build_prompt(analysis)

    screenplay = await llm_service.complete(
        system, user_prompt, temperature=0.7, model=state.get("llm_model")
    )

    return {
        "screenplay": screenplay,
        "screenplay_approved": False,
        "current_stage": "screenplay_written",
    }
