"""episodes 仓储:集 CRUD + 项目状态聚合(纯函数,不落库)。

一个 Project 含多个 Episode;每集是一条独立流水线(thread=episode.id)。
"""
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Episode
from drama_agent.db.enums import LifecycleStatus


def _to_dict(row: Episode) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "episode_number": row.episode_number,
        "title": row.title,
        "script_id": row.script_id,
        "status": row.status,
        "llm_model": row.llm_model,
        "video_provider": row.video_provider,
        "video_model": row.video_model,
        "resolution": row.resolution,
        "state_snapshot": row.state_snapshot,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def aggregate_project_status(episode_statuses: list[str]) -> str:
    """按各集状态聚合出项目展示态(取最活跃优先)。纯函数。"""
    s = set(episode_statuses)
    if not s:
        return "empty"
    if s & {LifecycleStatus.RUNNING.value, LifecycleStatus.QUEUED.value}:
        return "running"
    if LifecycleStatus.PAUSED.value in s:
        return "paused"
    if episode_statuses and all(st == LifecycleStatus.COMPLETED.value for st in episode_statuses):
        return "completed"
    if LifecycleStatus.FAILED.value in s:
        return "partial_failed"
    return "running"  # 兜底:有集但非上述终态,视为进行中


async def create(
    session: AsyncSession, *, project_id: str, title: str, script_id: str,
    llm_model: str, video_provider: str, video_model: str, resolution: str,
    episode_number: int | None = None,
    use_keyframes: bool = False, keyframe_image_model: str = "",
) -> dict:
    """建一集(引用一个 completed Script)。episode_number 不传则自动取 project 下 max+1。"""
    if episode_number is None:
        current_max = (await session.execute(
            select(func.coalesce(func.max(Episode.episode_number), 0))
            .where(Episode.project_id == project_id)
        )).scalar() or 0
        episode_number = current_max + 1
    row = Episode(
        id=str(uuid.uuid4()), project_id=project_id, episode_number=episode_number,
        title=title, script_id=script_id, status=LifecycleStatus.CREATED.value,
        llm_model=llm_model, video_provider=video_provider,
        video_model=video_model, resolution=resolution,
        use_keyframes=use_keyframes, keyframe_image_model=keyframe_image_model,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def get(session: AsyncSession, episode_id: str) -> dict | None:
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    return _to_dict(row) if row else None


async def list_by_project(session: AsyncSession, project_id: str) -> list[dict]:
    rows = (await session.execute(
        select(Episode).where(Episode.project_id == project_id)
        .order_by(Episode.episode_number.asc())
    )).scalars().all()
    return [_to_dict(r) for r in rows]


async def project_status(session: AsyncSession, project_id: str) -> str:
    """读该项目所有集状态并聚合。"""
    rows = (await session.execute(
        select(Episode.status).where(Episode.project_id == project_id)
    )).scalars().all()
    return aggregate_project_status(list(rows))
