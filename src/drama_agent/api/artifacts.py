from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.session import get_db
from drama_agent.services import artifact_service
from drama_agent.services.video_actions import ACTIONS, available_actions
from drama_agent.services.video_service import video_service

router = APIRouter(prefix="/api/episodes", tags=["artifacts"])


@router.get("/{episode_id}/shots/{shot_id}/artifacts")
async def list_artifacts(episode_id: str, shot_id: str, db: AsyncSession = Depends(get_db)):
    return {"artifacts": await artifact_service.list_by_shot(db, episode_id, shot_id)}


@router.get("/{episode_id}/artifacts/{artifact_id}/actions")
async def list_actions(episode_id: str, artifact_id: str, db: AsyncSession = Depends(get_db)):
    artifact = await artifact_service.get(db, artifact_id)
    if not artifact or artifact["episode_id"] != episode_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"actions": available_actions(artifact)}


@router.post("/{episode_id}/artifacts/{artifact_id}/actions/{action_id}")
async def run_action(
    episode_id: str,
    artifact_id: str,
    action_id: str,
    params: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    artifact = await artifact_service.get(db, artifact_id)
    if not artifact or artifact["episode_id"] != episode_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    action = ACTIONS.get(action_id)
    if not action:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action_id}")
    provider = video_service.get_provider(artifact["provider"])
    if not action.available(artifact, provider):
        raise HTTPException(
            status_code=400, detail=f"Action {action_id} not available for this artifact"
        )
    new_fields = await action.execute(artifact, params or {})
    child = await artifact_service.create_child(db, artifact, new_fields)
    return {"artifact": child}
