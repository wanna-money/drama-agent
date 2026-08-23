from drama_agent.workflow.state import DramaState, PromptDict
from drama_agent.workflow.constants import ReferenceRole, SHOT_TYPE_DESC
from drama_agent.knowledge.store import knowledge_store
from drama_agent.db import session as db_session
from drama_agent.services import character_service
from drama_agent.services.llm_service import llm_service

SYSTEM = """You are an expert video generation prompt engineer.
Create precise, effective prompts for AI video generation models.
Focus on visual elements: subject, action, environment, lighting, camera, mood, quality."""


def _guide_key_for(model_id: str) -> str | None:
    """解析视频模型 → 其 prompt_guide_key;未知模型(resolve 抛 ValueError)降级 None。"""
    from drama_agent import provider as provider_pkg
    try:
        _p, m = provider_pkg.provider_registry.resolve_model(model_id)
        return m.prompt_guide_key
    except ValueError:
        return None


def build_prompt(
    shot: dict,
    char_descriptions: list[str],
    templates: list[str],
    cin_rules: list[str],
    provider: str,
    guides: list[str] | None = None,
    notes: str | None = None,
) -> tuple[str, str]:
    """构造视频 prompt 生成的 (system, user)。RAG 结果由调用方查好后注入,保持纯函数。
    notes 是人工审核退回时的修改意见(见 prompt_engineer_node);首次生成时为 None/空,
    此时不输出任何"意见"相关文本段落——避免 LLM 看到空白占位、误当成一条真实指令。
    """
    context = f"""
Shot info:
- Type: {shot["shot_type"]} ({SHOT_TYPE_DESC.get(shot["shot_type"], shot["shot_type"])})
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

Video provider: {provider}
Model-specific prompt guide:
{chr(10).join(f"- {g}" for g in (guides or [])) if guides else "- (no model-specific guide; write a clear, cinematic prompt in the language that model expects)"}
"""
    notes = (notes or "").strip()
    if notes:
        context += f"""
Revision notes (human reviewer rejected the previous version and asked for this change — you MUST address it):
{notes}
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
    return SYSTEM, user_prompt


async def prompt_engineer_node(state: DramaState) -> dict:
    shots = state["shots"]
    provider = state.get("video_provider", "seedance")
    project_id = state["project_id"]
    revision_notes = state.get("prompt_revision_notes") or None
    prompts: list[PromptDict] = []

    if not shots:
        return {"prompts": prompts, "prompts_approved": False, "current_stage": "prompts_ready"}

    async with db_session.AsyncSessionLocal() as session:
        # 一次运行只有一个视频模型 → guide 全镜头共用,循环外解析一次
        guide_key = _guide_key_for(provider)
        guides = knowledge_store.retrieve("prompt_guide", key=guide_key) if guide_key else []
        for i, shot in enumerate(shots):
            # 领域知识:Dify 检索(失败降级常量),按镜头类型/运镜取
            tmpl_key = f"{guide_key}:{shot['shot_type']}" if guide_key else shot["shot_type"]
            templates = knowledge_store.retrieve("prompt_template", key=tmpl_key, k=2)
            cin_rules = knowledge_store.retrieve("cinematography", key="camera", k=1)

            # 角色外貌上下文(PG)
            char_descriptions = []
            for char_name in shot.get("characters", []):
                desc = await character_service.get(session, project_id, char_name)
                if desc:
                    char_descriptions.append(f"{char_name}: {desc}")

            # Determine reference image for continuity — actual URL filled in by video_generator
            reference_image_url = None
            reference_role = None
            if i > 0:
                reference_role = ReferenceRole.FIRST_FRAME.value

            # For character shots, also consider subject_reference
            if shot.get("characters") and state.get("character_references"):
                first_char = shot["characters"][0]
                if first_char in state["character_references"]:
                    reference_image_url = state["character_references"][first_char]
                    reference_role = ReferenceRole.SUBJECT_REFERENCE.value

            system, user_prompt = build_prompt(
                shot, char_descriptions, templates, cin_rules, provider, guides, notes=revision_notes)

            result = await llm_service.complete_json(
                system, user_prompt, temperature=0.4, model=state.get("llm_model"))

            prompt: PromptDict = {
                "shot_id": shot["shot_id"],
                "prompt_text": result.get("prompt_text", shot["description"]),
                "negative_prompt": result.get(
                    "negative_prompt", "blurry, low quality, watermark"),
                "reference_image_url": reference_image_url,
                "reference_role": reference_role,
                "approved": False,
                "edited_prompt": None,
                "edited_negative_prompt": None,
                "keyframe_url": None,
            }
            prompts.append(prompt)

    return {
        "prompts": prompts,
        "prompts_approved": False,
        "current_stage": "prompts_ready",
    }
