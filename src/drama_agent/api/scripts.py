"""scripts API:剧本库(只读复用素材)。

剧本库不再有创作/审核流程 —— 只读列表/详情、删除、以及「从某集存入」。
剧本审核(AI 改写/编辑/版本回退)已搬到剧集页,端点在 workflow.py 的
`/episodes/{id}/screenplay/*`。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.services import script_service

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


class SaveFromEpisodeRequest(BaseModel):
    episode_id: str


@router.post("")
async def save_script_from_episode(
    req: SaveFromEpisodeRequest, db: AsyncSession = Depends(get_db)
):
    """把某集已通过的剧本另存为素材(手动点「存入剧本库」)。"""
    row = await script_service.create_from_episode(db, req.episode_id)
    if row is None:
        raise HTTPException(status_code=409, detail="该集剧本尚未通过或正文为空")
    return row


@router.get("")
async def list_scripts(project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    return await script_service.list_scripts(db, project_id=project_id)


@router.get("/{script_id}")
async def get_script(script_id: str, db: AsyncSession = Depends(get_db)):
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return row


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    ok = await script_service.delete(db, script_id)
    if not ok:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return {"ok": True}
