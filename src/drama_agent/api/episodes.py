"""集(Episode)子资源 CRUD。流水线端点在 workflow.py。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.models import Project, Episode, Job, Event, VideoArtifact, Script
from drama_agent.db.enums import LifecycleStatus
from drama_agent.services import episode_service, cost_service, story_service

router = APIRouter(prefix="/api/projects", tags=["episodes"])


def _default_llm_model() -> str:
    """默认文本模型 = provider 注册表的有效默认(is_default 优先,否则首个可用)。

    与 runner._fallback_llm_model / config_api 同源(规范 4):默认模型只有一处权威,
    不在接口层再写一份字符串。
    """
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    return dm.id if dm else ""


class CreateEpisodeRequest(BaseModel):
    """建一集。二选一表达"拍什么":

    · story_id  → 拍这段原文(从故事开跑;剧本由流水线产出)
    · script_id → 拍这个改编方案(直达分镜;原文由方案的 story_id 解析出来)
    两个都给时以 script_id 为准并校验二者一致 —— 静默取一个会让调用方以为另一个也生效。
    """
    title: str
    story_id: str | None = None
    script_id: str | None = None
    target_seconds: int = 120
    # 不给模型名写死默认值:默认模型的唯一权威是 provider 注册表的
    # effective_default("llm")(规范 4)。此处写死会与用户在「模型管理」标的默认模型分叉,
    # 未传该字段的调用方就会建出跑在别的 provider 上的集。
    llm_model: str | None = None
    video_provider: str = "seedance"
    video_model: str = ""
    resolution: str = "768P"
    # 画面比例:合法取值随模型不同,权威在 provider 注册表(Model.aspect_ratios);
    # 前端从 /config/video-models 拿选项,不自带一份写死的列表。
    aspect_ratio: str = "9:16"
    episode_number: int | None = None
    use_keyframes: bool = False
    keyframe_image_model: str = ""


class UpdateEpisodeRequest(BaseModel):
    """开拍前可改的字段。都是可选 —— 只改传了的那些。

    故事正文不在此列:它属于剧本(PATCH /scripts/{id}),集只是引用。
    """
    title: str | None = None
    target_seconds: int | None = None


@router.get("/{project_id}/episodes")
async def list_episodes(project_id: str, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    episodes = await episode_service.list_by_project(db, project_id)
    # 逐集算成本(N+1;单项目集数量级小,先接受)
    for e in episodes:
        agg = await cost_service.aggregate_entity(db, e["id"])
        e["cost_total"] = agg["total"]
        e["cost_unpriced"] = agg["unpriced"]
    return episodes


@router.post("/{project_id}/episodes", response_model=dict)
async def create_episode(
    project_id: str, req: CreateEpisodeRequest, db: AsyncSession = Depends(get_db)
):
    project = (await db.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not (req.story_id or req.script_id):
        raise HTTPException(status_code=422, detail="须指定拍什么:story_id(原文)或 script_id(改编方案)")
    script = None
    if req.script_id:
        script = (await db.execute(
            select(Script).where(Script.id == req.script_id)
        )).scalar_one_or_none()
        if script is None:
            raise HTTPException(status_code=404, detail="源剧本不存在")
        if not script.story_id:
            # 未迁移的旧行:没有原文归属就定不出集的锚点,不猜一个空 Story
            raise HTTPException(status_code=409, detail="该剧本没有原文归属,无法开拍")
        if req.story_id and req.story_id != script.story_id:
            raise HTTPException(
                status_code=422, detail="story_id 与该剧本所属的原文不一致")
    story_id = script.story_id if script else req.story_id
    story = await story_service.row_of(db, story_id or "")
    if story is None:
        raise HTTPException(status_code=404, detail="原文不存在")
    # 只要求有内容可推进:有剧本正文 → 直达分镜;只有原文 → 从故事分析起跑。
    # 两者皆空则无从下手。
    if not ((script.content if script else "") or "").strip() \
            and not (story.content or "").strip():
        raise HTTPException(status_code=409, detail="既无剧本正文也无故事原文,无法开拍")
    return await episode_service.create(
        db, project_id=project_id, title=req.title,
        story_id=story_id or "", script_id=req.script_id,
        target_seconds=req.target_seconds,
        llm_model=req.llm_model or _default_llm_model(),
        video_provider=req.video_provider,
        video_model=req.video_model, resolution=req.resolution,
        aspect_ratio=req.aspect_ratio, episode_number=req.episode_number,
        use_keyframes=req.use_keyframes,
        keyframe_image_model=req.keyframe_image_model,
    )


@router.patch("/{project_id}/episodes/{episode_id}")
async def update_episode(
    project_id: str, episode_id: str, req: UpdateEpisodeRequest,
    db: AsyncSession = Depends(get_db),
):
    """开拍前修改本集(标题/目标时长)。

    只允许 created 态改:一旦开拍,分镜的时长收敛已按当前目标算过,回头改它会让
    已产出的内容与目标不符。跑起来之后要改内容,走剧本审核的 AI 改写/手动编辑
    (那条路专为改内容设计,且有版本树)。
    """
    ep = (await db.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    if not ep or ep.project_id != project_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    if ep.status != LifecycleStatus.CREATED.value:
        raise HTTPException(
            status_code=409,
            detail=f"已开拍的剧集不能改故事内容（当前状态：{ep.status}）。"
                   "如需调整内容，请在剧本审核阶段使用 AI 改写或手动编辑。",
        )
    if req.title is not None:
        if not req.title.strip():
            raise HTTPException(status_code=422, detail="标题不能为空")
        ep.title = req.title.strip()
    if req.target_seconds is not None:
        if req.target_seconds <= 0:
            raise HTTPException(status_code=422, detail="目标时长须为正数")
        ep.target_seconds = req.target_seconds
    await db.commit()
    return await episode_service.get(db, episode_id)


@router.get("/{project_id}/episodes/{episode_id}")
async def get_episode(project_id: str, episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = await episode_service.get(db, episode_id)
    if not ep or ep["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    agg = await cost_service.aggregate_entity(db, episode_id)
    return {**ep, "cost_total": agg["total"], "cost_unpriced": agg["unpriced"]}


@router.delete("/{project_id}/episodes/{episode_id}")
async def delete_episode(project_id: str, episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = (await db.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    if not ep or ep.project_id != project_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    # 级联清理该集的 jobs/events/artifacts
    await db.execute(delete(Job).where(Job.episode_id == episode_id))
    await db.execute(delete(Event).where(Event.episode_id == episode_id))
    await db.execute(delete(VideoArtifact).where(VideoArtifact.episode_id == episode_id))
    await db.delete(ep)
    await db.commit()
    return {"ok": True}
