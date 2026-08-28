from drama_agent.workflow.state import DramaState, PromptDict
from drama_agent.workflow.constants import ReferenceRole, SHOT_TYPE_DESC
from drama_agent.workflow.prompt_rules import system_prompt
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

SYSTEM = system_prompt("""You are an expert video generation prompt engineer.
Create precise, effective prompts for AI video generation models.
Focus on visual elements: subject, action, environment, lighting, camera, mood, quality.""")

# 未上传参考图/模型无专属指引时的默认负向提示词(中文,与输出语言规则一致)
DEFAULT_NEGATIVE_PROMPT = "模糊、画质低、水印、字幕、文字叠加、肢体畸变"


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
{chr(10).join(f"- {g}" for g in (guides or [])) if guides else "- (无该模型专属指引,按通用电影化写法组织画面)"}
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
  "negative_prompt": "{DEFAULT_NEGATIVE_PROMPT}、..."
}}"""
    return SYSTEM, user_prompt


async def prompt_engineer_node(state: DramaState) -> dict:
    from drama_agent.services import character_entity_service as ce
    shots = state["shots"]
    provider = state.get("video_provider", "seedance")
    revision_notes = state.get("prompt_revision_notes") or None
    cast = state.get("cast") or {}
    prompts: list[PromptDict] = []

    if not shots:
        return {"prompts": prompts, "prompts_approved": False, "current_stage": "prompts_ready"}

    # 一次运行只有一个视频模型 → guide 全镜头共用,循环外解析一次
    guide_key = _guide_key_for(provider)
    guides = knowledge_store.retrieve("prompt_guide", key=guide_key) if guide_key else []
    for i, shot in enumerate(shots):
        # 领域知识:Dify 检索(失败降级常量),按镜头类型/运镜取
        tmpl_key = f"{guide_key}:{shot['shot_type']}" if guide_key else shot["shot_type"]
        templates = knowledge_store.retrieve("prompt_template", key=tmpl_key, k=2)
        cin_rules = knowledge_store.retrieve("cinematography", key="camera", k=1)

        # 角色外貌上下文:按 cast 的 character_id 取(**不按名字 join**)——
        # 角色改名后仍取得到,这是 cast_review 确认身份换来的收益。
        char_descriptions = []
        for char_name in shot.get("characters", []):
            cid = cast.get(char_name)
            if not cid:
                continue
            desc = await ce.get_appearance(cid)
            if desc:
                char_descriptions.append(f"{char_name}: {desc}")

        # 首帧连贯标记(实际 URL 由 video_generator 用上一镜末帧填)。
        # 角色主体参考图**不在这里取** —— 那条路已收敛到 subject_ref_service,
        # 否则同一角色的图会被这里和 video_generator 各投一次(规范 4)。
        reference_image_url = None
        reference_role = ReferenceRole.FIRST_FRAME.value if i > 0 else None

        system, user_prompt = build_prompt(
            shot, char_descriptions, templates, cin_rules, provider, guides, notes=revision_notes)

        result = await llm_service.complete_json(
            system, user_prompt, temperature=0.4, model=state.get("llm_model"))

        prompt: PromptDict = {
            "shot_id": shot["shot_id"],
            "prompt_text": result.get("prompt_text", shot["description"]),
            "negative_prompt": result.get(
                "negative_prompt", DEFAULT_NEGATIVE_PROMPT),
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
