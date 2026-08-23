"""用量记账:从 contextvar 取归属,独立短事务写 usage_records。非关键旁路,失败不抛。"""
import uuid

import structlog

from drama_agent.db import session as db_session
from drama_agent.db.enums import UsageKind
from drama_agent.db.models import UsageRecord
from drama_agent.workflow.usage_context import current_usage_context

logger = structlog.get_logger()


async def _write(kind: str, provider: str, model: str, *, input_tokens: int = 0,
                 output_tokens: int = 0, video_seconds: int = 0, calls: int = 1,
                 attribution: dict | None = None) -> None:
    ctx = attribution or current_usage_context()
    if not ctx or not ctx.get("entity_id"):
        return  # 无归属 → no-op,不写脏数据
    try:
        async with db_session.AsyncSessionLocal() as s:
            s.add(UsageRecord(
                id=str(uuid.uuid4()), entity_id=ctx["entity_id"],
                project_id=ctx.get("project_id", ""), is_script=bool(ctx.get("is_script", False)),
                node=ctx.get("node", ""), kind=kind, provider=provider, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
                video_seconds=video_seconds, calls=calls,
            ))
            await s.commit()
    except Exception as e:  # 非关键旁路:失败不阻断主流程
        logger.warning("usage_record_failed", kind=kind, model=model, error=str(e))


async def record_llm(usage: dict, provider: str, model: str) -> None:
    await _write(UsageKind.LLM.value, provider, model,
                 input_tokens=int(usage.get("input", 0)), output_tokens=int(usage.get("output", 0)))


async def record_image(usage: dict, provider: str, model: str) -> None:
    await _write(UsageKind.IMAGE.value, provider, model,
                 input_tokens=int(usage.get("input", 0)), output_tokens=int(usage.get("output", 0)))


async def record_video(*, provider: str, model: str, seconds: int, calls: int = 1,
                       entity_id: str | None = None, project_id: str | None = None,
                       is_script: bool | None = None, node: str | None = None) -> None:
    attribution = None
    if entity_id is not None:  # 脱离图场景(如产物动作):显式归属(来自 VideoArtifact)
        attribution = {"entity_id": entity_id, "project_id": project_id or "",
                       "is_script": bool(is_script), "node": node or ""}
    await _write(UsageKind.VIDEO.value, provider, model,
                 video_seconds=seconds, calls=calls, attribution=attribution)
