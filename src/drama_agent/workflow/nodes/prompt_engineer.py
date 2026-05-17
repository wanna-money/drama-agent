from drama_agent.workflow.state import DramaState, ShotDict, PromptDict
from drama_agent.services.llm_service import llm_service
from drama_agent.services.rag_service import rag_service

SYSTEM = """You are an expert video generation prompt engineer.
Create precise, effective prompts for AI video generation models.
Focus on visual elements: subject, action, environment, lighting, camera, mood, quality."""


async def prompt_engineer_node(state: DramaState) -> dict:
    shots = state["shots"]
    provider = state.get("video_provider", "seedance")
    project_id = state["project_id"]
    prompts: list[PromptDict] = []

    for i, shot in enumerate(shots):
        # RAG: get relevant templates and rules
        templates = rag_service.query_prompt_templates(
            shot["shot_type"], provider, n_results=2
        )
        cin_rules = rag_service.query_cinematography(
            f"{shot['shot_type']} {shot['camera_movement']}", n_results=1
        )

        # Build character appearance context
        char_descriptions = []
        for char_name in shot.get("characters", []):
            desc = rag_service.get_character_description(project_id, char_name)
            if desc:
                char_descriptions.append(f"{char_name}: {desc}")

        # Determine reference image for continuity — actual URL filled in by video_generator
        reference_image_url = None
        reference_role = None
        if i > 0:
            reference_role = "first_frame"  # video_generator will set the actual URL

        # For character shots, also consider subject_reference
        if shot.get("characters") and state.get("character_references"):
            first_char = shot["characters"][0]
            if first_char in state["character_references"]:
                reference_image_url = state["character_references"][first_char]
                reference_role = "subject_reference"

        context = f"""
Shot info:
- Type: {shot["shot_type"]} ({_shot_type_desc(shot["shot_type"])})
- Camera: {shot["camera_movement"]}
- Duration: {shot["duration_seconds"]}s
- Location: {shot["location"]}
- Description: {shot["description"]}
- Action: {shot["action"]}
- Dialogue: {shot["dialogue"] or "none"}
- Characters: {", ".join(shot["characters"]) or "no characters"}

Character appearances:
{chr(10).join(char_descriptions) or "No characters in this shot"}

Reference prompt templates:
{chr(10).join(templates)}

Cinematography rules:
{chr(10).join(cin_rules)}

Video provider: {provider} ({'Use concise English, cinematic terms' if provider == 'seedance' else 'Can use Chinese, be descriptive'})
"""

        user_prompt = f"""{context}

Generate:
1. A detailed video generation prompt (2-4 sentences, include character appearances verbatim if characters present)
2. A negative prompt (things to avoid)

Return JSON:
{{
  "prompt_text": "...",
  "negative_prompt": "blurry, low quality, watermark, text overlay, ..."
}}"""

        result = await llm_service.complete_json(SYSTEM, user_prompt, temperature=0.4, model=state.get("llm_model"))

        prompt: PromptDict = {
            "shot_id": shot["shot_id"],
            "prompt_text": result.get("prompt_text", shot["description"]),
            "negative_prompt": result.get(
                "negative_prompt", "blurry, low quality, watermark"
            ),
            "reference_image_url": reference_image_url,
            "reference_role": reference_role,
            "approved": False,
            "edited_prompt": None,
        }
        prompts.append(prompt)

    return {
        "prompts": prompts,
        "prompts_approved": False,
        "current_stage": "prompts_ready",
    }


def _shot_type_desc(shot_type: str) -> str:
    descs = {
        "ELS": "Extreme Long Shot - vast environment",
        "LS": "Long Shot - full body visible",
        "MS": "Medium Shot - waist up",
        "CU": "Close-Up - face fills frame",
        "ECU": "Extreme Close-Up - eyes/hands detail",
    }
    return descs.get(shot_type, shot_type)
