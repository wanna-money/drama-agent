"""内置 provider 声明 → DB(幂等 seed + 对账)。

代码里的内置声明(provider/llm|video|image/providers.py)是种子数据源,启动时对账 DB:
1. 缺失的内置 provider → 插入(builtin=True);首次插入 api_key 取 env 现值。
2. 已存在的内置 provider → 只把 base_url 对齐到声明的官方地址(base_url 锁死、UI 只读);
   api_key / models / enabled 是用户可改字段,不覆盖。
3. 声明里已删除的旧内置 provider(如下线的 bailian-video)→ 删除(内置 UI 删不掉,靠此清理)。
   仅动 builtin=True 的行;用户自定义(builtin=False)一律不碰。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def seed_providers() -> int:
    """把代码内置声明幂等对账进 DB。返回新插入条数。

    无 DB / 表不存在 / 异常 → 记 warning 并返回已插入数(不阻断启动)。
    """
    from drama_agent import provider as provider_pkg
    from drama_agent.db import session as db_session
    from drama_agent.db.models import CustomProvider

    builtins = provider_pkg._builtin_providers()
    by_id = {p.id: p for p in builtins}
    builtin_ids = set(by_id)
    inserted = 0
    try:
        async with db_session.AsyncSessionLocal() as s:
            rows = (await s.execute(select(CustomProvider))).scalars().all()
            existing = {r.provider_id: r for r in rows}

            # 1) 插入缺失的内置 provider
            for p in builtins:
                if p.id in existing:
                    continue
                kind = p.models[0].kind if p.models else "llm"
                s.add(CustomProvider(
                    id=str(uuid.uuid4()),
                    provider_id=p.id,
                    label=p.label,
                    protocol=p.protocol,
                    kind=kind,
                    base_url=p.base_url,
                    api_key=p.resolve_credential(),  # env 现值(解析 $ENV / 明文)
                    models_json=[m.model_dump() for m in p.models],
                    enabled=p.enabled,
                    builtin=True,
                ))
                inserted += 1

            for r in rows:
                if not r.builtin:
                    continue  # 用户自定义 provider 一律不碰
                if r.provider_id not in builtin_ids:
                    # 3) 声明里已删除的旧内置(如 bailian-video)→ 清理
                    await s.delete(r)
                elif r.base_url != by_id[r.provider_id].base_url:
                    # 2) 对齐官方 base_url(锁死字段;不动 api_key/models/enabled)
                    r.base_url = by_id[r.provider_id].base_url

            await s.commit()
    except Exception as e:  # noqa: BLE001 — seed 失败不应阻断启动
        logger.warning("seed_providers failed: %s", e)
    return inserted
