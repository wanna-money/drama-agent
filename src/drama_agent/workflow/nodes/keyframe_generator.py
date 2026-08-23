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
    updated: list[PromptDict] = []
    for p in state["prompts"]:
        if p.get("keyframe_url"):        # 已有(resume/未被打回)→ 保留,不重生成
            updated.append(p)
            continue
        prompt_text = p.get("edited_prompt") or p["prompt_text"]
        try:
            images = await asset_gen_service.generate_image(
                model_id, prompt_text, size="1024x576", n=1)
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
