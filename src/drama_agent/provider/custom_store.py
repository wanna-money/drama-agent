"""自定义 provider 的 DB 读取 + 转换为 Provider。

CustomProvider(ORM 行)→ provider.base.Provider(+ 内联 Model)。
读取动态查 session(可测试重绑),失败降级为空列表(不阻断 registry 构建)。
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from drama_agent.provider.base import Model, Provider

logger = logging.getLogger(__name__)


def row_to_provider(row) -> Provider:
    """CustomProvider ORM 行 → Provider(models_json → [Model])。"""
    models = [Model(**m) for m in (row.models_json or [])]
    return Provider(
        id=row.provider_id,
        label=row.label,
        protocol=row.protocol,
        base_url=row.base_url,
        api_key=row.api_key,
        models=models,
    )


async def load_custom_providers() -> list[Provider]:
    """读 DB 里 enabled 的自定义 provider,转成 Provider 列表。
    无 DB / 表不存在 / 任意异常 → 返回 [](不阻断 registry 构建)。"""
    try:
        from drama_agent.db import session as db_session
        from drama_agent.db.models import CustomProvider
        async with db_session.AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(CustomProvider).where(CustomProvider.enabled == True)  # noqa: E712
            )).scalars().all()
        return [row_to_provider(r) for r in rows]
    except Exception as e:
        logger.warning("load_custom_providers failed, skipping DB providers: %s", e)
        return []
