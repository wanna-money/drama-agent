"""事件写入/读取：状态变更与业务变更同事务写入，供 WebSocket 游标补拉。"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.models import Event
from drama_agent.db.enums import EventType
from drama_agent.db import dialect


def _to_dict(row: Event) -> dict:
    return {
        "id": row.id,
        "episode_id": row.episode_id,
        "project_id": row.project_id,
        "seq": row.seq,
        "type": row.type,
        "payload_json": row.payload_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def append_event(
    session: AsyncSession, episode_id: str, type: EventType, payload: dict,
    project_id: str = "",
) -> dict:
    """写一条事件并提交 —— 连同调用方在本 session 里已 flush 的业务变更**一并落库(同事务)**。

    seq 按 episode 自增;多实例并发写同一 episode 可能撞 `uq_event_seq`。
    事件插入放在 savepoint(begin_nested)里:冲突只回滚该插入(不动调用方已 flush 的
    业务变更如 ep.status),重算 seq 有界重试。project_id 为冗余列,便于按项目聚合。
    """
    row: Event | None = None
    for _ in range(5):
        seq = await dialect.next_event_seq(session, episode_id)
        candidate = Event(
            episode_id=episode_id, project_id=project_id, seq=seq,
            type=type.value, payload_json=payload,
        )
        try:
            async with session.begin_nested():  # savepoint:仅隔离事件插入的冲突
                session.add(candidate)
        except IntegrityError:
            continue  # 撞 uq_event_seq → savepoint 已回滚,重算 seq 再试
        row = candidate
        break
    if row is None:
        raise RuntimeError(f"append_event: seq 冲突重试仍失败 (episode={episode_id})")
    await session.commit()  # 提交外层事务:事件 + 调用方业务变更
    await session.refresh(row)
    return _to_dict(row)


async def fetch_since(
    session: AsyncSession, episode_id: str, after_seq: int, limit: int = 200
) -> list[dict]:
    result = await session.execute(
        select(Event)
        .where(Event.episode_id == episode_id, Event.seq > after_seq)
        .order_by(Event.seq.asc())
        .limit(limit)
    )
    return [_to_dict(r) for r in result.scalars().all()]
