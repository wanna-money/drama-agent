"""jobs 仓储：幂等入队、原子领取、心跳、回收僵尸。"""
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.models import Job
from drama_agent.db.enums import JobKind, JobStatus
from drama_agent.db import dialect


def _to_dict(row: Job) -> dict:
    return {
        "id": row.id, "episode_id": row.episode_id, "project_id": row.project_id,
        "kind": row.kind, "status": row.status,
        "owner": row.owner, "heartbeat_at": row.heartbeat_at, "attempts": row.attempts,
        "max_attempts": row.max_attempts, "dedup_key": row.dedup_key,
        "payload_json": row.payload_json, "error_message": row.error_message,
    }


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def enqueue(
    session: AsyncSession, kind: JobKind, episode_id: str,
    dedup_key: str, payload: dict | None = None, project_id: str = "",
) -> dict:
    """幂等入队:命中 (episode_id, kind, dedup_key) 既有则返回,不新建。
    project_id 为冗余列,便于按项目聚合查询。"""
    existing = (await session.execute(
        select(Job).where(
            Job.episode_id == episode_id, Job.kind == kind.value, Job.dedup_key == dedup_key
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value):
            return _to_dict(existing)  # 非终态:真去重,防同一 resume 被重复处理
        # 终态(succeeded/failed):重新武装该行 → 允许"审核打回后的新决策"重新入队。
        # job 是运行时编排记录(非审计日志,审计走 events),复用行以满足 UNIQUE(episode,kind,dedup_key)。
        existing.status = JobStatus.QUEUED.value
        existing.payload_json = payload
        existing.owner = None
        existing.heartbeat_at = None
        existing.attempts = 0
        existing.error_message = None
        await session.commit()
        await session.refresh(existing)
        return _to_dict(existing)
    row = Job(
        id=str(uuid.uuid4()), episode_id=episode_id, project_id=project_id, kind=kind.value,
        status=JobStatus.QUEUED.value, dedup_key=dedup_key, payload_json=payload,
    )
    session.add(row)
    try:
        await session.commit()
    except Exception:
        # 并发下唯一约束冲突 → 回滚后查既有返回(幂等)
        await session.rollback()
        row = (await session.execute(
            select(Job).where(
                Job.episode_id == episode_id, Job.kind == kind.value,
                Job.dedup_key == dedup_key,
            )
        )).scalar_one()
        return _to_dict(row)
    await session.refresh(row)
    return _to_dict(row)


async def claim_next(session: AsyncSession, owner: str) -> dict | None:
    return await dialect.claim_one_job(session, owner)


async def heartbeat(session: AsyncSession, job_id: str) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id).values(heartbeat_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def mark_succeeded(session: AsyncSession, job_id: str) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id).values(status=JobStatus.SUCCEEDED.value)
    )
    await session.commit()


async def mark_failed(session: AsyncSession, job_id: str, error: str) -> None:
    await session.execute(
        update(Job).where(Job.id == job_id)
        .values(status=JobStatus.FAILED.value, error_message=error)
    )
    await session.commit()


async def requeue(session: AsyncSession, job_id: str) -> None:
    row = await session.get(Job, job_id)
    if row is None:
        return
    row.attempts += 1
    row.status = JobStatus.QUEUED.value
    row.owner = None
    row.heartbeat_at = None
    await session.commit()


async def fail_or_requeue(session: AsyncSession, job_id: str, error: str) -> str:
    """按 **DB 真值** attempts 决定重试还是判死(不依赖调用方领取时的快照,避免与
    reap_stale 递增脱节)。未超 max → requeue(attempts+1),否则 → failed。
    返回 "requeued" / "failed" / "gone"(job 不存在)。"""
    row = await session.get(Job, job_id)
    if row is None:
        return "gone"
    if row.attempts + 1 < row.max_attempts:
        row.attempts += 1
        row.status = JobStatus.QUEUED.value
        row.owner = None
        row.heartbeat_at = None
        await session.commit()
        return "requeued"
    row.status = JobStatus.FAILED.value
    row.error_message = error
    await session.commit()
    return "failed"


async def reap_stale(session: AsyncSession, timeout_seconds: int) -> int:
    """running 且心跳超时的 job：未超 max_attempts → requeue，否则 failed。返回处理数。"""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    rows = (await session.execute(
        select(Job).where(Job.status == JobStatus.RUNNING.value)
    )).scalars().all()
    count = 0
    for row in rows:
        hb = _as_utc(row.heartbeat_at)
        if hb is not None and hb >= cutoff:
            continue  # 心跳仍新鲜
        if row.attempts + 1 < row.max_attempts:
            row.attempts += 1
            row.status = JobStatus.QUEUED.value
            row.owner = None
            row.heartbeat_at = None
        else:
            row.status = JobStatus.FAILED.value
            row.error_message = "reaped: heartbeat timeout, max attempts exceeded"
        count += 1
    await session.commit()
    return count
