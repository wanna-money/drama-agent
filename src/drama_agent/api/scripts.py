"""scripts API:剧本 —— 一段原文的一个改编方案(与 Story 是 N 侧)。

建剧本只有一个来源:`POST ""` 带 episode_id,把某集的成稿存入。从文本入库产出的是
**原文**,走 `/api/stories`(见那里的说明)—— 让本路由兼管文本入库的话,建出来的
东西不会出现在剧本列表里,名字与实际产物对不上。

剧本审核(AI 改写/编辑/版本回退)仍在剧集页,端点在 workflow.py 的
`/episodes/{id}/screenplay/*` —— 那是**制作中**某一集的内容,与库里的复用素材不同。
原文正文 / story_analysis / cast 要改去 `/api/stories/{id}`(权威在 Story)。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.services import script_service

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


class CreateScriptRequest(BaseModel):
    """把某集的成稿存入。文本入库走 POST /api/stories(产出的是原文,不是剧本)。"""
    episode_id: str


class UpdateScriptRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    # 归属:传作品 id = 移过去;传空串 = 解绑成散稿;不传 = 不动
    # (空串而非 null 表达"清空",否则与"未传"无法区分)
    project_id: str | None = None


@router.post("")
async def create_script(req: CreateScriptRequest, db: AsyncSession = Depends(get_db)):
    """把某集已通过的剧本另存为复用素材:挂在**同一段原文**下,成为它的又一个方案。"""
    row = await script_service.create_from_episode(db, req.episode_id)
    if row is None:
        raise HTTPException(status_code=409, detail="该集剧本尚未通过、正文为空,或源剧本没有原文归属")
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


@router.patch("/{script_id}")
async def update_script(
    script_id: str, req: UpdateScriptRequest, db: AsyncSession = Depends(get_db)
):
    """改剧本(只改传了的字段)。此处只改**剧本正文** ——
    原文 / story_analysis / cast 要改去 PATCH /api/stories/{id}(权威在 Story)。"""
    if req.title is not None and not req.title.strip():
        raise HTTPException(status_code=422, detail="剧本标题不能为空")
    row = await script_service.update(
        db, script_id,
        title=req.title.strip() if req.title is not None else None,
        content=req.content,
        project_id=(req.project_id or None) if req.project_id else None,
        unset_project=req.project_id == "",
    )
    if row is None:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return row


class DeleteManyRequest(BaseModel):
    script_ids: list[str]


@router.post("/batch-delete")
async def delete_scripts(req: DeleteManyRequest, db: AsyncSession = Depends(get_db)):
    """整组删除(如一本小说切出的全部分集)。

    用 POST 而非 DELETE:要带一个 id 列表的请求体,而 DELETE 带体在代理/网关上
    支持不一。仍有集引用其中任一剧本 → 409 并告知集数:集的 script_id 必填,
    删掉在用的剧本会让那些集再也跑不起来(且删除不可撤销)。
    """
    ids = [i for i in req.script_ids if i]
    if not ids:
        raise HTTPException(status_code=422, detail="未指定要删除的剧本")
    used = await script_service.referencing_episodes(db, ids)
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {used} 集在用这些剧本，请先删除对应剧集再删剧本")
    return {"deleted": await script_service.delete_many(db, ids)}


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    # 与批量删同一守卫:集的 script_id 必填,删掉在用的剧本会让那些集跑不起来
    used = await script_service.referencing_episodes(db, [script_id])
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {used} 集在用这个剧本，请先删除对应剧集再删剧本")
    ok = await script_service.delete(db, script_id)
    if not ok:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return {"ok": True}
