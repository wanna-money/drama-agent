"""提示词优化端点(中立,供图像/关键帧/视频复用)。"""
from fastapi import APIRouter
from pydantic import BaseModel

from drama_agent.services.prompt_optimize_service import optimize_prompt

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


class OptimizeIn(BaseModel):
    raw_prompt: str
    kind: str = "image"          # "image" | "video"
    target_model: str | None = None
    subject: str | None = None   # "character" 时追加人物四视图设定板要求


@router.post("/optimize")
async def optimize(body: OptimizeIn):
    optimized = await optimize_prompt(
        body.raw_prompt, kind=body.kind, target_model=body.target_model, subject=body.subject)
    return {"optimized": optimized}
