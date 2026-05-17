from drama_agent.workflow.state import DramaState, StoryAnalysis, CharacterProfile
from drama_agent.services.llm_service import llm_service
from drama_agent.services.rag_service import rag_service

SYSTEM = """You are a professional story analyst for short drama productions.
Analyze the given story and extract structured information needed for screenplay adaptation.
Focus on characters (with detailed visual appearance descriptions), setting, plot, and tone."""


async def story_analyzer_node(state: DramaState) -> dict:
    user_prompt = f"""Analyze this story for short drama production:

STORY:
{state["raw_input"]}

GENRE: {state.get("genre", "drama")}

Return JSON with this exact structure:
{{
  "title": "story title",
  "genre": "drama/romance/thriller/comedy/action",
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

    analysis_data = await llm_service.complete_json(SYSTEM, user_prompt, temperature=0.3, model=state.get("llm_model"))

    # Save character profiles to RAG for later use in prompt generation
    project_id = state["project_id"]
    for char in analysis_data.get("characters", []):
        name = char.get("name", "")
        appearance = char.get("appearance", "")
        if name and appearance:
            rag_service.save_character_profile(project_id, name, appearance)

    return {
        "story_analysis": analysis_data,
        "title": analysis_data.get("title", state.get("title", "Untitled")),
        "current_stage": "story_analyzed",
    }
