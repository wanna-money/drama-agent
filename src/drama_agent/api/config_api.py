from fastapi import APIRouter
from drama_agent.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/models")
async def list_models():
    """Return available LLM models for the frontend dropdown."""
    return {"models": settings.llm_models}


@router.get("/video-models")
async def list_video_models():
    """Return available video models for the frontend dropdown."""
    return {"models": settings.video_models}
