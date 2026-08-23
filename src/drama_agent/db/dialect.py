"""DB 方言适配：把 PG/SQLite 差异集中在此，业务层不写 dialect 判断。"""
from datetime import datetime, timezone
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.models import Job, Event
from drama_agent.db.enums import JobStatus


def _dialect(session: AsyncSession) -> str:
    bind = session.bind
    return bind.dialect.name if bind is not None else "sqlite"


async def next_event_seq(session: AsyncSession, episode_id: str) -> int:
    """事务内取该 episode 的下一个事件序号(seq 按集自增)。"""
    result = await session.execute(
        select(func.coalesce(func.max(Event.seq), 0)).where(Event.episode_id == episode_id)
    )
    return (result.scalar() or 0) + 1


async def claim_one_job(session: AsyncSession, owner: str) -> dict | None:
    """原子领取一个 queued job → running。PG 用 SKIP LOCKED，SQLite 用原子 UPDATE。"""
    now = datetime.now(timezone.utc)
    if _dialect(session) == "postgresql":
        row = (await session.execute(
            select(Job).where(Job.status == JobStatus.QUEUED.value)
            .order_by(Job.created_at.asc()).limit(1)
            .with_for_update(skip_locked=True)
        )).scalar_one_or_none()
        if row is None:
            return None
        row.status = JobStatus.RUNNING.value
        row.owner = owner
        row.heartbeat_at = now
        await session.commit()
        return _job_to_dict(row)

    # SQLite 降级：库级写锁下，原子 UPDATE 抢占单条
    candidate = (await session.execute(
        select(Job.id).where(Job.status == JobStatus.QUEUED.value)
        .order_by(Job.created_at.asc()).limit(1)
    )).scalar_one_or_none()
    if candidate is None:
        return None
    res = await session.execute(
        update(Job).where(Job.id == candidate, Job.status == JobStatus.QUEUED.value)
        .values(status=JobStatus.RUNNING.value, owner=owner, heartbeat_at=now)
    )
    await session.commit()
    if res.rowcount == 0:  # type: ignore[attr-defined]  # CursorResult 运行时有 rowcount
        return None
    row = (await session.execute(select(Job).where(Job.id == candidate))).scalar_one()
    return _job_to_dict(row)


def _job_to_dict(row: Job) -> dict:
    return {
        "id": row.id, "episode_id": row.episode_id, "project_id": row.project_id,
        "kind": row.kind, "status": row.status,
        "owner": row.owner, "heartbeat_at": row.heartbeat_at, "attempts": row.attempts,
        "max_attempts": row.max_attempts, "dedup_key": row.dedup_key,
        "payload_json": row.payload_json, "error_message": row.error_message,
    }
