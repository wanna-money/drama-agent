"""作品级「小说改编 → 分集切分」端点。

设计见 docs/superpowers/specs/2026-08-25-novel-adaptation-episode-split-design.md
所有写接口都带状态守卫 + 幂等(规范 3)。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.session import get_db
from drama_agent.db.models import Project
from drama_agent.db.enums import AdaptationStatus, JobKind
from drama_agent.services import adaptation_service, job_service, script_service

router = APIRouter(prefix="/api/projects", tags=["adaptation"])


class CommitRequest(BaseModel):
    llm_model: str | None = None
    video_provider: str | None = None
    video_model: str = ""
    resolution: str | None = None
    use_keyframes: bool = False


async def _get_project(db: AsyncSession, project_id: str) -> Project:
    p = (await db.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return p


@router.post("/{project_id}/adapt")
async def start_adaptation(project_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_project(db, project_id)
    if not (p.source_text or "").strip():
        raise HTTPException(status_code=422, detail="该作品没有小说正文,无法改编")
    if bool(p.target_episodes) == bool(p.target_seconds_per_episode):
        raise HTTPException(status_code=422, detail="切分依据须二选一:集数 或 每集时长")
    if p.adaptation_status in (AdaptationStatus.ANALYZING.value,
                               AdaptationStatus.ADAPTING.value):
        raise HTTPException(status_code=409, detail="改编正在进行中")
    if p.adaptation_status == AdaptationStatus.CAST_REVIEW.value:
        raise HTTPException(status_code=409, detail="请先确认角色身份,再继续改编")
    # 先置状态再入队:enqueue 内部会 commit(job_service.py),那次 commit 会把这里改脏的
    # Project 和新 Job 一并刷下去 → 天然单事务。反过来写就是两个事务,中间崩溃会留下
    # 「队列里有 ADAPT job、作品却仍是 none」的错位(界面显示未改编,后台已在跑)。
    # 先抽角色(analyzing),确认后才进 adapting 切分 —— 角色必须在切分前确立,
    # 否则各段自行发明称呼,同一角色跨集漂移(见 runner._run_adaptation)
    p.adaptation_status = AdaptationStatus.ANALYZING.value
    p.cast_pending = []
    # enqueue 对已终态的同 dedup_key job 会自动复位重跑(见 job_service.enqueue),
    # 覆盖"重新改编"场景,这里不用再手动复位。
    job = await job_service.enqueue(
        db, JobKind.ADAPT, project_id, dedup_key="adapt", project_id=project_id)
    return {"job_id": job["id"], "adaptation_status": p.adaptation_status}


async def _adaptation_state(db: AsyncSession, p: Project) -> dict:
    """对外的改编态形状(唯一权威)。

    scripts 是切分产出的**实际去处**(剧本库),不再有 adapted_draft 那样的中间草稿 ——
    面板据此展示切出了哪些剧本,编辑则去剧本详情页。
    """
    return {
        "adaptation_status": p.adaptation_status,
        "source_text": p.source_text or "",
        "target_episodes": p.target_episodes,
        "target_seconds_per_episode": p.target_seconds_per_episode,
        "scripts": await script_service.list_scripts(db, project_id=p.id),
        # 非空即表示停在角色确认卡点(前端据此渲染确认面板)
        "cast_pending": p.cast_pending or [],
    }


@router.get("/{project_id}/adaptation")
async def get_adaptation(project_id: str, db: AsyncSession = Depends(get_db)):
    p = await _get_project(db, project_id)
    return await _adaptation_state(db, p)


class ConfirmCastRequest(BaseModel):
    """角色名 → {action: link|create, character_id?}。未给决策的名字按新建处理。"""
    cast: dict[str, dict[str, str]] = {}


@router.post("/{project_id}/adaptation/confirm-cast")
async def confirm_cast(project_id: str, req: ConfirmCastRequest,
                       db: AsyncSession = Depends(get_db)):
    """确认整本小说的角色身份,随后继续切分。

    确认与继续切分必须一起完成:只落身份不重新入队,作品会停在 adapting 却没有任务在跑。
    """
    await _get_project(db, project_id)
    result = await adaptation_service.confirm_cast(db, project_id, req.cast)
    if result is None:
        raise HTTPException(status_code=409, detail="当前状态不需要确认角色")
    # 复用同一 dedup_key:enqueue 对已终态的同 key job 会复位重跑(见 job_service.enqueue),
    # 于是 worker 再跑一次 _run_adaptation,这次因状态已是 adapting 而直接进切分。
    job = await job_service.enqueue(
        db, JobKind.ADAPT, project_id, dedup_key="adapt", project_id=project_id)
    return {**result, "job_id": job["id"]}


@router.post("/{project_id}/adaptation/commit")
async def commit_adaptation(project_id: str, req: CommitRequest,
                            db: AsyncSession = Depends(get_db)):
    p = await _get_project(db, project_id)
    if p.adaptation_status != AdaptationStatus.DONE.value:
        raise HTTPException(status_code=409, detail="当前状态不可建集")
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    vm = provider_pkg.provider_registry.effective_default("video")
    try:
        created = await adaptation_service.commit(
            db, project_id,
            llm_model=req.llm_model or (dm.id if dm else ""),
            video_provider=req.video_provider or (vm.id if vm else ""),
            video_model=req.video_model,
            resolution=req.resolution or "768P",
            use_keyframes=req.use_keyframes)
    except IntegrityError as exc:
        # 集号已由 create 自动避让,故正常不可达;并发建集仍可能撞 uq_episode_number。
        # 映射成 409 而非裸 500:commit 是整体回滚的,重试即可(规范 6 的错误映射)。
        raise HTTPException(status_code=409, detail="集号冲突,请重试建集") from exc
    if created is None:
        raise HTTPException(status_code=409, detail="没有可建集的剧本")
    # 状态仍是 done:剧本还在剧本库里,可以再建一次集(比如加拍一集),不是一次性的
    return {"episodes": created, "adaptation_status": p.adaptation_status}
