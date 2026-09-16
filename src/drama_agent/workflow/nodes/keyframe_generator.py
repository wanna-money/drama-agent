import structlog

from drama_agent.services import asset_gen_service
from drama_agent.services.storage_service import storage_service
from drama_agent.workflow.state import DramaState, PromptDict

logger = structlog.get_logger()

_DEFAULT_IMAGE_MODEL = "doubao-seedream-3-0-t2i"


async def keyframe_generator_node(state: DramaState) -> dict:
    """逐镜文生图出关键帧静图,写 PromptDict.keyframe_url。单镜失败不拖垮整批。"""
    project_id = state["project_id"]
    model_id = state.get("keyframe_image_model") or _DEFAULT_IMAGE_MODEL
    # 风格锚点:视频 prompt 里的风格短语是"讲给 LLM 听、指望它写进 prompt_text"的
    # 软约束(见 prompt_engineer.build_prompt),用户编辑过 prompt 或模型漂移都可能
    # 丢失。关键帧走 asset_gen_service 同一条确定性兜底(拼接固定风格短语),
    # 与角色立绘/素材库生图对齐,不能让关键帧单独漏掉这层保证。
    visual_style = state.get("visual_style", "")
    updated: list[PromptDict] = []
    for p in state["prompts"]:
        if p.get("keyframe_url"):        # 已有(resume/未被打回)→ 保留,不重生成
            updated.append(p)
            continue
        prompt_text = p.get("edited_prompt") or p["prompt_text"]
        try:
            images = await asset_gen_service.generate_image(
                model_id, prompt_text, size="1024x576", n=1, visual_style=visual_style)
            if images:
                name, _ = await storage_service.save_project_image(
                    project_id, images[0], f"{p['shot_id']}.png", image_type="keyframe")
                url = f"/api/projects/{project_id}/images/keyframe/{name}"
                updated.append({**p, "keyframe_url": url})
            else:
                updated.append(p)
        except Exception as e:  # noqa: BLE001 — 单镜关键帧失败不阻断整批出片
            logger.warning("keyframe generation failed", shot_id=p["shot_id"], error=str(e))
            updated.append(p)
    return {"prompts": updated, "current_stage": "keyframes_ready"}
