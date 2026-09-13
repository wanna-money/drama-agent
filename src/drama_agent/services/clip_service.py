"""clips 仓储:建散片、查、置状态。

状态跃迁由 mark_* 各自**自开短事务**完成:它们跑在 worker 的执行链路里,
调用点没有 request-scoped session。
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db import session as db_session
from drama_agent.db.enums import ClipTaskType, LifecycleStatus
from drama_agent.db.models import Clip


def _to_dict(row: Clip) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "prompt": row.prompt,
        "negative_prompt": row.negative_prompt,
        "duration": row.duration,
        "resolution": row.resolution,
        "aspect_ratio": row.aspect_ratio,
        "video_provider": row.video_provider,
        "video_model": row.video_model,
        "seed": row.seed,
        "references_json": row.references_json,
        "audio_refs_json": row.audio_refs_json,
        "video_refs_json": row.video_refs_json,
        "task_type": row.task_type,
        "storage_key": row.storage_key,
        "status": row.status,
        "error_message": row.error_message,
        "task_id": row.task_id,
        "video_url": row.video_url,
        "local_path": row.local_path,
        "revised_prompt": row.revised_prompt,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create(
    session: AsyncSession, *, project_id: str, prompt: str,
    negative_prompt: str | None = None, duration: int = 5,
    resolution: str = "", aspect_ratio: str = "",
    video_provider: str = "", video_model: str = "",
    references: list[dict] | None = None, audio_refs: list[dict] | None = None,
    video_refs: list[dict] | None = None,
    task_type: str = ClipTaskType.REFERENCE.value,
) -> dict:
    """建一条散片请求,初始 queued。

    **不 commit** —— 调用方随后 enqueue,由 enqueue 内部那次 commit 把
    clip 行与 job 行一并落库(单事务)。分两次提交会留下"队列里有 job、
    clips 表里没有那一行"的错位。
    """
    row = Clip(
        id=str(uuid.uuid4()), project_id=project_id, prompt=prompt,
        negative_prompt=negative_prompt, duration=duration,
        resolution=resolution, aspect_ratio=aspect_ratio,
        video_provider=video_provider, video_model=video_model,
        references_json=references, audio_refs_json=audio_refs,
        video_refs_json=video_refs, task_type=task_type,
        status=LifecycleStatus.QUEUED.value,
    )
    session.add(row)
    await session.flush()
    return _to_dict(row)


async def get(session: AsyncSession, clip_id: str) -> dict | None:
    row = (await session.execute(
        select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    return _to_dict(row) if row else None


async def list_by_project(session: AsyncSession, project_id: str) -> list[dict]:
    rows = (await session.execute(
        select(Clip).where(Clip.project_id == project_id)
        .order_by(Clip.created_at.desc(), Clip.id.desc())
    )).scalars().all()
    return [_to_dict(r) for r in rows]


async def delete(session: AsyncSession, clip_id: str) -> bool:
    row = (await session.execute(
        select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def _update(clip_id: str, **fields) -> None:
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Clip).where(Clip.id == clip_id))).scalar_one_or_none()
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        await s.commit()


async def mark_running(clip_id: str) -> None:
    await _update(clip_id, status=LifecycleStatus.RUNNING.value)


async def mark_completed(
    clip_id: str, *, task_id: str, video_url: str | None, local_path: str | None,
    seed: int | None = None, revised_prompt: str | None = None,
    duration: int | None = None,
) -> None:
    """置完成并**清掉 error_message** —— 留着会让重跑成功的散片仍显示上次的失败原因。"""
    fields: dict = dict(
        status=LifecycleStatus.COMPLETED.value, error_message=None,
        task_id=task_id, video_url=video_url, local_path=local_path,
        seed=seed, revised_prompt=revised_prompt,
    )
    # 只在平台回传了真实时长时才覆盖:提交 -1(编辑任务)时这一列必须被改写,
    # 否则记账会按 -1 算出负数秒。回传缺失时保留提交值,不写回 None。
    if duration is not None and duration > 0:
        fields["duration"] = duration
    await _update(clip_id, **fields)


async def mark_failed(clip_id: str, error: str) -> None:
    await _update(clip_id, status=LifecycleStatus.FAILED.value, error_message=error)


async def set_storage_key(clip_id: str, key: str) -> None:
    """记下本片的公网 storage key(供之后被引用为编辑/延长的输入)。"""
    await _update(clip_id, storage_key=key)
