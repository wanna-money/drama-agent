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
from drama_agent.services import adaptation_service, job_service
from drama_agent.services.adaptation_service import MAX_DRAFT_EPISODES

router = APIRouter(prefix="/api/projects", tags=["adaptation"])


class DraftItem(BaseModel):
    index: int
    title: str
    screenplay: str


class SaveDraftRequest(BaseModel):
    draft: list[DraftItem]


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
    if p.adaptation_status == AdaptationStatus.ADAPTING.value:
        raise HTTPException(status_code=409, detail="改编正在进行中")
    if p.adaptation_status == AdaptationStatus.COMMITTED.value:
        raise HTTPException(status_code=409, detail="已按草稿建过集,不能重新改编")
    # 先置状态再入队:enqueue 内部会 commit(job_service.py),那次 commit 会把这里改脏的
    # Project 和新 Job 一并刷下去 → 天然单事务。反过来写就是两个事务,中间崩溃会留下
    # 「队列里有 ADAPT job、作品却仍是 none」的错位(界面显示未改编,后台已在跑)。
    p.adaptation_status = AdaptationStatus.ADAPTING.value
    # enqueue 对已终态的同 dedup_key job 会自动复位重跑(见 job_service.enqueue),
    # 覆盖"重新改编"场景,这里不用再手动复位。
    job = await job_service.enqueue(
        db, JobKind.ADAPT, project_id, dedup_key="adapt", project_id=project_id)
    return {"job_id": job["id"], "adaptation_status": p.adaptation_status}


def _adaptation_state(p: Project) -> dict:
    """对外的改编态形状(唯一权威)。GET 与 PUT 都走这里 —— 两处各自拼 dict 迟早分叉,
    而前端把 PUT 结果直接 setState,少一个键就会踩空(少 source_text 会让面板整块消失)。
    """
    return {
        "adaptation_status": p.adaptation_status,
        "adapted_draft": p.adapted_draft or [],
        "source_text": p.source_text or "",
        "target_episodes": p.target_episodes,
        "target_seconds_per_episode": p.target_seconds_per_episode,
    }


@router.get("/{project_id}/adaptation")
async def get_adaptation(project_id: str, db: AsyncSession = Depends(get_db)):
    return _adaptation_state(await _get_project(db, project_id))


@router.put("/{project_id}/adaptation/draft")
async def put_draft(project_id: str, req: SaveDraftRequest,
                    db: AsyncSession = Depends(get_db)):
    p = await _get_project(db, project_id)
    # 入参校验是这里的**实质防线**:save_draft 会规整草稿并丢弃没有正文的段,
    # 放行畸形入参 = 用户草稿被静默规整成空、接口却回 200。
    if not req.draft:
        raise HTTPException(status_code=422, detail="分集草稿不能为空")
    if any(not i.screenplay.strip() for i in req.draft):
        raise HTTPException(status_code=422, detail="每集都必须有剧本正文")
    # 上限沿用规整逻辑的 MAX_DRAFT_EPISODES(不在这里另写字面量,免得两处分叉)。
    # 放行 = 规整时被 `raw[:MAX]` 悄悄截断,用户多出来的集丢了却还回 200。
    if len(req.draft) > MAX_DRAFT_EPISODES:
        raise HTTPException(
            status_code=422, detail=f"分集数量超出上限({MAX_DRAFT_EPISODES} 集)")
    saved = await adaptation_service.save_draft(
        db, project_id, [i.model_dump() for i in req.draft])
    if saved is None:
        raise HTTPException(status_code=409, detail="当前状态不可编辑分集草稿")
    # 兜底哨兵:上面的入参校验保证规整不丢段,故正常不可达。留着是为了规整规则日后
    # 变化时**能被发现**而非静默清空(注意 save_draft 已落库,这里只报错不能回滚)。
    if not saved["adapted_draft"]:
        raise HTTPException(status_code=422, detail="分集草稿无有效内容")
    # 回 GET 的全形状(而非 save_draft 的 service 层两字段返回)—— 前端拿 PUT 结果直接
    # setState。p 与 save_draft 用的是同一 session,commit 后已是最新值。
    return _adaptation_state(p)


@router.post("/{project_id}/adaptation/commit")
async def commit_adaptation(project_id: str, req: CommitRequest,
                            db: AsyncSession = Depends(get_db)):
    p = await _get_project(db, project_id)
    if p.adaptation_status != AdaptationStatus.DRAFT_READY.value:
        raise HTTPException(status_code=409, detail="当前状态不可建集")
    # 空草稿必须拦在这里:放行会「建 0 集却置 committed」,而 committed 既不能再建集
    # 也不能重新改编 → 作品零集且无路可走,只能删库重建。
    if not p.adapted_draft:
        raise HTTPException(status_code=422, detail="分集草稿为空,无法建集")
    if any(not str((i or {}).get("screenplay", "")).strip() for i in p.adapted_draft):
        raise HTTPException(status_code=422, detail="草稿中存在没有正文的分集")
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
        raise HTTPException(status_code=409, detail="当前状态不可建集")
    return {"episodes": created, "adaptation_status": AdaptationStatus.COMMITTED.value}
