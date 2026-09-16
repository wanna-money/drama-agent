import structlog

from drama_agent.workflow.state import DramaState, PromptDict
from drama_agent.workflow.constants import (
    ReferenceRole, SHOT_TYPE_DESC, LIGHTING_PHRASE, COLOR_TEMP_PHRASE, VISUAL_STYLE_PHRASE,
    generation_duration_for,
)
from drama_agent.workflow.prompt_rules import system_prompt
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service

SYSTEM = system_prompt("""You are an expert video generation prompt engineer.
Create precise, effective prompts for AI video generation models.
Focus on visual elements: subject, action, environment, lighting, camera, mood, quality.""")

logger = structlog.get_logger()

# 未上传参考图/模型无专属指引时的默认负向提示词(中文,与输出语言规则一致)
DEFAULT_NEGATIVE_PROMPT = "模糊、画质低、水印、字幕、文字叠加、肢体畸变"

# 单个镜头的 prompt 生成尝试次数。**逐镜重试而非整节点重跑**:模型偶发不返回
# prompt_text,整批重跑等于把所有镜头的骰子重掷一次 —— 12 镜的运行里几乎必有一镜
# 再次失败(实测每次失败在不同镜号)。逐镜只重掷那一个。
_PER_SHOT_ATTEMPTS = 3


def _same_text(a: str, b: str) -> bool:
    """两段文本是否实质相同(忽略空白与中英标点差异)。

    用于判断模型是否把分镜描述原样抄回来。只判**等价**,不判包含 ——
    正常的扩写结果几乎必然包含原句,按包含拒会误伤。
    """
    trans = str.maketrans("", "", " \t\n\r，。、；：！？,.;:!?…—-·「」“”\"'()（）")
    return a.translate(trans) == b.translate(trans)


def _guide_key_for(model_id: str) -> str | None:
    """解析视频模型 → 其 prompt_guide_key;未知模型(resolve 抛 ValueError)降级 None。"""
    from drama_agent import provider as provider_pkg
    try:
        _p, m = provider_pkg.provider_registry.resolve_model(model_id)
        return m.prompt_guide_key
    except ValueError:
        return None


def _supports_timestamp_prompt(model_id: str) -> bool:
    """目标模型是否响应 prompt 里的镜内时间轴;解析不到时保守判 False。

    False 是更安全的默认:把镜内时间轴写给不认它的模型,第二段动作会被
    静默忽略;而对认时间轴的模型少用一次该能力,只是少写了一句可选指令。
    """
    from drama_agent import provider as provider_pkg
    try:
        _p, m = provider_pkg.provider_registry.resolve_model(model_id)
        return m.supports_timestamp_prompt
    except ValueError:
        return False


def build_prompt(
    shot: dict,
    char_descriptions: list[str],
    templates: list[str],
    cin_rules: list[str],
    provider: str,
    guides: list[str] | None = None,
    notes: str | None = None,
    supports_timestamp_prompt: bool = False,
    visual_style: str = "",
) -> tuple[str, str]:
    """构造视频 prompt 生成的 (system, user)。RAG 结果由调用方查好后注入,保持纯函数。
    notes 是人工审核退回时的修改意见(见 prompt_engineer_node);首次生成时为 None/空,
    此时不输出任何"意见"相关文本段落——避免 LLM 看到空白占位、误当成一条真实指令。

    supports_timestamp_prompt 决定镜内时间轴的指令区文案:目标模型不认它时必须明写
    禁止,否则模型会把该镜头写成"镜头1/镜头2"两段动作,而不认时间轴的模型只响应
    镜头序号,第二段动作会被静默忽略(成片里凭空少一半内容)。
    """
    # 光影查表译成中文短语,而不是把枚举值原样丢给 LLM 自己翻译 —— 后者每镜译法不同,
    # 分镜声明的"同场景光影一致"到 prompt 层就散掉了。
    light = LIGHTING_PHRASE.get(shot.get("lighting", ""), "")
    temp = COLOR_TEMP_PHRASE.get(shot.get("color_temp", ""), "")
    light_line = "、".join(x for x in (light, temp) if x) or "(未指定,按场景合理选择)"
    style_line = VISUAL_STYLE_PHRASE.get(visual_style, "")
    # beats(镜内节拍合并镜)只有目标模型认时间轴才展开成时间轴文本 ——
    # 不认时间轴的模型只响应镜头序号,写了时间轴也不会被执行(见下方 timestamp instruction)。
    # 没有 beats 的镜头此段为空,prompt 与改动前完全一致(回归判据)。
    beats = shot.get("beats") or []
    beats_block = ""
    if beats and supports_timestamp_prompt:
        duration = shot["duration_seconds"]
        beats_lines = "\n".join(f"{i}. {b}" for i, b in enumerate(beats, 1))
        beats_block = f"""
镜内节拍(按顺序,总长 {duration} 秒,用官方时间轴形态如 0-3s：…… 写进 prompt):
{beats_lines}
"""
    context = f"""
Shot info:
- Type: {shot["shot_type"]} ({SHOT_TYPE_DESC.get(shot["shot_type"], shot["shot_type"])})
- Camera: {shot["camera_movement"]}
- 光影(必须写进 prompt,不得改成别的方案): {light_line}
{f"- 视觉风格(必须写进 prompt,不得改成别的方案): {style_line}" if style_line else ""}
- Duration: {shot["duration_seconds"]}s
- Location: {shot["location"]}
- Description: {shot["description"]}
- Action: {shot["action"]}
- Dialogue: {shot["dialogue"] or "none"}
- Characters: {", ".join(shot["characters"]) or "no characters"}
{beats_block}

Character appearances:
{chr(10).join(char_descriptions) or "No characters in this shot"}

Reference prompt templates:
{chr(10).join(templates)}

Cinematography rules:
{chr(10).join(cin_rules)}

Video provider: {provider}
Model-specific prompt guide:
{chr(10).join(f"- {g}" for g in (guides or [])) if guides else "- (无该模型专属指引,按通用电影化写法组织画面)"}

Timestamp instruction ({"TIMESTAMP-CAPABLE" if supports_timestamp_prompt else "NOT timestamp-capable"}):
{
    "该模型认镜内时间轴,若单镜时长内需要多段动作,用官方形态标注 0-3s：…… 3-8s：……"
    if supports_timestamp_prompt else
    "一条 prompt 只描述一个连续动作。禁止出现「镜头2」「随后切到」「接着」这类跨镜表述"
    "——该模型只响应镜头序号,写了也不会被执行,第二段动作会在成片里静默消失。"
}
"""
    notes = (notes or "").strip()
    if notes:
        context += f"""
Revision notes (human reviewer rejected the previous version and asked for this change — you MUST address it):
{notes}
"""

    user_prompt = f"""{context}

Generate:
1. A detailed video generation prompt (2-4 sentences, include character appearances verbatim if characters present).
   光影必须照上面「光影」一行写入 —— 那是分镜定下的场景基调,改掉它同一场戏的画面就会跳
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

    # 一次运行只有一个视频模型 → guide/时间轴能力全镜头共用,循环外解析一次。
    # 解析键用 video_model(真正的模型 id);它为空时才退到 provider,
    # 与 video_generator.py 解析 provider/resolution 的口径一致(规范 4)。
    model_ref = state.get("video_model") or provider
    guide_key = _guide_key_for(provider)
    guides = knowledge_store.retrieve("prompt_guide", key=guide_key) if guide_key else []
    timestamp_capable = _supports_timestamp_prompt(model_ref)
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
            shot, char_descriptions, templates, cin_rules, provider, guides, notes=revision_notes,
            supports_timestamp_prompt=timestamp_capable,
            visual_style=state.get("visual_style", ""))

        # **逐镜重试**,而不是让一个镜头的偶发空返回作废整批(规范 6:单元素失败
        # 不得拖垮整体)。模型偶尔不返回 prompt_text —— 实测一次 12 镜的运行里
        # 每次重试失败在**不同**镜号(4/6/9),因为整节点重跑等于把 12 个镜头的
        # 骰子全部重掷一次;逐镜只重掷那一个,一次多花一次调用而非报废 11 个成品。
        result = {}
        for attempt in range(_PER_SHOT_ATTEMPTS):
            result = await llm_service.complete_json(
                system, user_prompt, temperature=0.4, model=state.get("llm_model"))
            candidate = str(result.get("prompt_text") or "").strip()
            if candidate and not _same_text(candidate, shot.get("description") or ""):
                break
            if attempt + 1 < _PER_SHOT_ATTEMPTS:
                logger.warning(
                    "prompt 生成不合格,该镜重试",
                    shot_number=shot.get("shot_number"), attempt=attempt + 1,
                    reason="空返回" if not candidate else "原样复述分镜描述")

        # 拿不到**扩写**结果就抛错交 job 重试,**不得让分镜 description 充数**:
        # 那是一句叙事描述,没有光线/镜头/画质约束,视频模型据此产出的画面明显掉档,
        # 而界面上它与正常 prompt 一样"有内容",用户无从判断这个镜头为何特别差。
        # 两种失败形态都要拦(实测各出现过):
        #   · 没返回 prompt_text(旧代码退回 description);
        #   · 返回了,但把 description 一字不改地抄回来(键在,故"非空"守卫拦不住)。
        # 只做**等价**判断,不设长度阈值:在描述基础上扩写的正常结果必然包含原句,
        # 按"包含"或"太短"拒会误伤(短镜头的合格 prompt 也可以不长)。
        text = str(result.get("prompt_text") or "").strip()
        if not text:
            raise ValueError(
                f"镜 {shot.get('shot_number')} 的 prompt 生成失败:模型未返回 prompt_text")
        if _same_text(text, shot.get("description") or ""):
            raise ValueError(
                f"镜 {shot.get('shot_number')} 的 prompt 生成失败:"
                "模型原样复述了分镜描述,未产出视觉化 prompt")

        prompt: PromptDict = {
            "shot_id": shot["shot_id"],
            "prompt_text": text,
            "negative_prompt": result.get(
                "negative_prompt", DEFAULT_NEGATIVE_PROMPT),
            "reference_image_url": reference_image_url,
            "reference_role": reference_role,
            "approved": False,
            "edited_prompt": None,
            "edited_negative_prompt": None,
            "keyframe_url": None,
            # 现算一次,video_generator 只读 —— 与角色外貌走 character_id 同一原则。
            "generation_duration_seconds": generation_duration_for(
                shot["duration_seconds"], model_ref),
        }
        prompts.append(prompt)

    return {
        "prompts": prompts,
        "prompts_approved": False,
        "current_stage": "prompts_ready",
    }
