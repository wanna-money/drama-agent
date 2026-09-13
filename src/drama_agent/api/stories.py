"""stories API:故事库 —— 原文是内容的源头,与剧本 1:N。

为什么文本入库在这里、不在 `/api/scripts`:粘一段文本产出的是**原文**,不是剧本
(剧本是它的改编方案,由制作流程或后续改编产出)。这两件事各有自己的资源:
  切分产出 Story(自指 parent_id) / 改编产出 Script(story_id)
让 `/api/scripts` 兼管文本入库的话,建出来的东西不会出现在剧本列表里 ——
名字与实际产物对不上,调用方无从判断该去哪个列表找它。

`/api/scripts` 只余「把某集成稿存入」一个来源(那才真的产出剧本)。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.session import get_db
from drama_agent.services import script_intake_service, story_service

router = APIRouter(prefix="/api/stories", tags=["stories"])


class CreateStoryRequest(BaseModel):
    project_id: str | None = None
    title: str | None = None
    content: str | None = None
    story_analysis: dict | None = None
    # 用户在界面上选的类型。story_analysis.genre 是分析产出的回显值,两者都缺时
    # 才落默认 drama —— 缺了这个字段,用户选的类型无法到达 Story,永远落到 drama。
    genre: str | None = None
    # analyze 返回的 pending 经用户确认后的决策:{名字: {action: link|create, character_id?}}
    cast: dict | None = None
    # 这段原文是某段更长原文切出来的(切分关系走 Story 自指)
    parent_id: str | None = None
    order_index: int = 0


class AnalyzeRequest(BaseModel):
    # project_id 可空:没有作品时无角色库可对齐,分析仍可做(pending 为空)
    project_id: str | None = None
    content: str
    llm_model: str | None = None


class UpdateStoryRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    story_analysis: dict | None = None
    cast: dict | None = None
    # 归属:传作品 id = 移过去;传空串 = 解绑成散稿;不传 = 不动
    # (空串而非 null 表达"清空",否则与"未传"无法区分)
    project_id: str | None = None


@router.post("/analyze")
async def analyze_story(req: AnalyzeRequest):
    """分析原文并对齐角色。不落库 —— 前端拿 pending 让用户确认后再提交创建。"""
    if not req.content.strip():
        raise HTTPException(status_code=422, detail="故事内容不能为空")
    return await script_intake_service.analyze(
        req.project_id, req.content, req.llm_model)


@router.post("")
async def create_story(req: CreateStoryRequest, db: AsyncSession = Depends(get_db)):
    """从一段文本建原文。

    project_id 可空:原文是全局可复用的内容,不必先有作品(不给即散稿)——
    要求必填会逼出"为了存一段故事先建个空作品"的怪操作。
    """
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="故事标题不能为空")
    if not (req.content or "").strip():
        raise HTTPException(status_code=422, detail="故事内容不能为空")
    return await script_intake_service.create_with_cast(
        db, project_id=req.project_id, title=title,
        source_text=req.content or "", story_analysis=req.story_analysis,
        genre=req.genre, cast_decisions=req.cast,
        parent_story_id=req.parent_id, order_index=req.order_index,
    )


@router.get("")
async def list_stories(
    project_id: str | None = None, parent_id: str | None = None,
    top_level_only: bool = False, db: AsyncSession = Depends(get_db),
):
    """原文列表。top_level_only 只列顶层(切出来的片段属于其父原文的内部结构,
    平铺在总览里会把一本小说的 N 段和别的故事混在一起)。"""
    return await story_service.list_stories(
        db, project_id=project_id, parent_id=parent_id, top_level_only=top_level_only)


@router.get("/{story_id}")
async def get_story(story_id: str, db: AsyncSession = Depends(get_db)):
    row = await story_service.get(db, story_id)
    if row is None:
        raise HTTPException(status_code=404, detail="故事不存在")
    return row


@router.patch("/{story_id}")
async def update_story(
    story_id: str, req: UpdateStoryRequest, db: AsyncSession = Depends(get_db)
):
    """改原文(只改传了的字段)。

    改原文**不会**自动更新已有的改编方案 —— 那些剧本是独立产出,要重新改编才会跟上。
    """
    if req.title is not None and not req.title.strip():
        raise HTTPException(status_code=422, detail="故事标题不能为空")
    row = await story_service.update(
        db, story_id,
        title=req.title.strip() if req.title is not None else None,
        content=req.content, story_analysis=req.story_analysis, cast=req.cast,
        project_id=(req.project_id or None) if req.project_id else None,
        unset_project=req.project_id == "",
    )
    if row is None:
        raise HTTPException(status_code=404, detail="故事不存在")
    return row


@router.delete("/{story_id}")
async def delete_story(story_id: str, db: AsyncSession = Depends(get_db)):
    """删原文,连同它切出的片段。

    仍有改编方案挂在它(或它的片段)下 → 409 并告知方案数:剧本的 story_id 指向它,
    删掉会让那些剧本再也取不到原文(提炼 prompt、重新改编都要读它),且删除不可撤销。
    """
    used = await story_service.referencing_scripts(db, [story_id])
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"还有 {used} 个改编方案挂在这个故事下，请先删除对应剧本再删故事")
    ok = await story_service.delete(db, story_id)
    if not ok:
        raise HTTPException(status_code=404, detail="故事不存在")
    return {"ok": True}
