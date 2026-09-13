"""项目(剧集元信息)CRUD。单集流水线在 episodes.py + workflow.py。"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from pydantic import BaseModel, Field
from drama_agent.db.session import get_db
from drama_agent.db.models import (
    Project, Episode, Job, Event, VideoArtifact, Script, Clip, Story, Character, Look,
)
from drama_agent.db.enums import AdaptationStatus, Genre, VisualStyle
from drama_agent.services import episode_service, cost_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    title: str
    genre: Genre = Genre.DRAMA   # 非法值由 pydantic 拒为 422
    visual_style: VisualStyle    # 无默认值,前端必须显式传;非法值同样由 pydantic 拒 422
    # 小说模式(可选):有正文时切分依据须恰好二选一
    source_text: str | None = None
    # 必须为正数:非正值会原样进改编 prompt(如"切成恰好 -3 集"),且 0 会被下面的
    # bool() 二选一校验当成"没给"
    target_episodes: int | None = Field(default=None, gt=0)
    target_seconds_per_episode: int | None = Field(default=None, gt=0)


@router.post("", response_model=dict)
async def create_project(req: CreateProjectRequest, db: AsyncSession = Depends(get_db)):
    if (req.source_text or "").strip() and (
        bool(req.target_episodes) == bool(req.target_seconds_per_episode)
    ):
        raise HTTPException(status_code=422, detail="切分依据须二选一:集数 或 每集时长")
    project = Project(
        id=str(uuid.uuid4()), title=req.title, genre=req.genre.value,
        visual_style=req.visual_style.value,
        source_text=req.source_text,
        target_episodes=req.target_episodes,
        target_seconds_per_episode=req.target_seconds_per_episode,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "visual_style": project.visual_style,
        "status": "empty",  # 新项目还没有集
        "adaptation_status": project.adaptation_status,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.get("")
async def list_projects(db: AsyncSession = Depends(get_db)):
    projects = (await db.execute(
        select(Project).order_by(Project.created_at.desc())
    )).scalars().all()
    out = []
    for p in projects:
        status = await episode_service.project_status(db, p.id)
        # 逐个项目算成本(N+1 查询;项目数量级小,先接受,必要时再改批量聚合)
        cost = await cost_service.project_total(db, p.id)
        out.append({
            "id": p.id,
            "title": p.title,
            "genre": p.genre,
            "visual_style": p.visual_style,
            "status": status,
            "cost_total": cost["total"],
            "cost_unpriced": cost["unpriced"],
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        })
    return out


@router.get("/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    episodes = await episode_service.list_by_project(db, project_id)
    status = episode_service.aggregate_project_status([e["status"] for e in episodes])
    cost = await cost_service.project_total(db, project_id)
    return {
        "id": project.id,
        "title": project.title,
        "genre": project.genre,
        "visual_style": project.visual_style,
        "status": status,
        "episodes": episodes,
        "cost_total": cost["total"],
        "cost_unpriced": cost["unpriced"],
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


class UpdateProjectRequest(BaseModel):
    title: str | None = None
    source_text: str | None = None
    visual_style: VisualStyle | None = None


@router.patch("/{project_id}")
async def update_project(
    project_id: str, req: UpdateProjectRequest, db: AsyncSession = Depends(get_db)
):
    """改作品(只改传了的字段)。

    小说正文只在改编开跑前可改:切分产出的剧本是从这段正文推导出来的,开跑后改它会让
    已切出的剧本与源头不符(而剧本已是独立的内容,不会随之更新)。要重来须先重新改编。
    """
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if req.title is not None:
        if not req.title.strip():
            raise HTTPException(status_code=422, detail="作品标题不能为空")
        project.title = req.title.strip()
    if req.visual_style is not None:
        project.visual_style = req.visual_style.value
    if req.source_text is not None:
        if project.adaptation_status != AdaptationStatus.NONE.value:
            raise HTTPException(
                status_code=409,
                detail="已开始改编，如需修改小说正文请先重新改编（现有剧本不会自动更新）")
        project.source_text = req.source_text
    await db.commit()
    return {"id": project.id, "title": project.title,
            "source_text": project.source_text or "",
            "visual_style": project.visual_style,
            "adaptation_status": project.adaptation_status}


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    # 级联清理该项目下所有集与散片,及其 jobs/events/artifacts(事务内)。
    # **新增一张挂 project_id 的表时必须同步登记在此**:漏掉的表会留下永久孤儿 ——
    # 作品已不在,界面上再没有任何入口能列出或删除它们。
    await db.execute(delete(Job).where(Job.project_id == project_id))
    await db.execute(delete(Event).where(Event.project_id == project_id))
    await db.execute(delete(VideoArtifact).where(VideoArtifact.project_id == project_id))
    await db.execute(delete(Episode).where(Episode.project_id == project_id))
    await db.execute(delete(Clip).where(Clip.project_id == project_id))
    # 剧本**不随作品删除**:它是全局可复用的内容,project_id 只记"产生于哪个作品"。
    # 但必须解绑成散稿 —— 留着指向已删作品的 id 就是悬空引用,剧本库按 id 分组时
    # 每个死 id 各成一组、标题全显示成「未命名作品」。
    await db.execute(
        update(Script).where(Script.project_id == project_id).values(project_id=None))
    # 原文**不随作品删除**:它与剧本同理,是全局可复用的内容(原文是内容的家)。
    # 但必须解绑 —— 留着指向已删作品的 id 就是悬空引用。
    await db.execute(
        update(Story).where(Story.project_id == project_id).values(project_id=None))
    # 角色卡属于作品(它的造型、参考图都是为这部作品配的),作品没了即无意义 → 删。
    # Look 挂在 Character 上(models.py 的 character_id,无外键,手工级联),
    # 故先删 Look 再删 Character,否则 Look 变成孤儿。
    await db.execute(delete(Look).where(Look.character_id.in_(
        select(Character.id).where(Character.project_id == project_id))))
    await db.execute(delete(Character).where(Character.project_id == project_id))
    await db.delete(project)
    await db.commit()
    return {"ok": True}
