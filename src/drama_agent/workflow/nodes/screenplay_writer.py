from drama_agent.workflow.state import DramaState
from drama_agent.services.llm_service import llm_service

SYSTEM = """You are a professional screenplay writer specializing in short dramas.
Write screenplays in standard format with scene headings, action lines, and dialogue.
Each scene should be self-contained and visually compelling."""


async def screenplay_writer_node(state: DramaState) -> dict:
    analysis = state["story_analysis"]

    char_list = "\n".join(
        f"- {c.get('name', 'Unknown')}: {c.get('appearance', '')} | {c.get('personality', '')}"
        for c in analysis.get("characters", [])
        if c.get("name")
    )

    user_prompt = f"""Write a complete short drama screenplay based on this analysis:

TITLE: {analysis.get("title")}
GENRE: {analysis.get("genre")}
SETTING: {analysis.get("setting")}
TONE: {analysis.get("tone")}
THEMES: {", ".join(analysis.get("themes", []))}
PLOT: {analysis.get("plot_summary")}

CHARACTERS:
{char_list}

Requirements:
- Use standard screenplay format (INT./EXT. LOCATION - DAY/NIGHT)
- Each scene should be 30-90 seconds when filmed
- Include clear action lines describing visual elements
- Write natural, character-appropriate dialogue
- Aim for {analysis.get("scene_count_estimate", 5)} scenes total
- Each scene should advance plot or reveal character
- End with a satisfying resolution

Write the complete screenplay now:"""

    screenplay = await llm_service.complete(
        SYSTEM, user_prompt, temperature=0.7, model=state.get("llm_model")
    )

    return {
        "screenplay": screenplay,
        "screenplay_approved": False,
        "current_stage": "screenplay_written",
    }
