"""成本估算:usage_records × 当前 Cost 单价(查询时算,不落库金额)。币种人民币,估算值。

单价来自 provider registry 的 Model.cost(动态查单例,与 llm/video 侧一致)。
未知 model / 未声明 Cost 的记录记为"未定价",金额按 0 计并在结果里置 unpriced 标记,
不因单条无价而让整份聚合失败。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent import provider as provider_pkg
from drama_agent.db.models import UsageRecord
from drama_agent.provider.base import Cost

_TOKENS_PER_UNIT = 1_000_000  # Cost.input/output 以每百万 token 计价


def _usage(rec: UsageRecord) -> tuple[int, int, int, int]:
    """取用量四元组;未 flush 的实例列默认尚未生效(为 None)→ 按 0 计。"""
    return (
        rec.input_tokens or 0,
        rec.output_tokens or 0,
        rec.video_seconds or 0,
        rec.calls or 0,
    )


def estimate_one(rec: UsageRecord, cost: Cost | None) -> tuple[float, bool]:
    """返回 (估算金额, 是否已定价)。cost 为空 → (0.0, False)。"""
    if cost is None:
        return 0.0, False
    in_tok, out_tok, seconds, calls = _usage(rec)
    amt = in_tok / _TOKENS_PER_UNIT * cost.input
    amt += out_tok / _TOKENS_PER_UNIT * cost.output
    amt += seconds * (cost.per_second or 0)
    amt += calls * (cost.per_call or 0)
    return round(amt, 4), True


def _cost_of(model: str, cache: dict[str, Cost | None]) -> Cost | None:
    """查该 model 当前单价;未知 model(registry 抛 ValueError)→ None。按 model 缓存。"""
    if model in cache:
        return cache[model]
    try:
        _provider, mdl = provider_pkg.provider_registry.resolve_model(model)
        cost = mdl.cost
    except ValueError:
        cost = None
    cache[model] = cost
    return cost


def _has_usage(rec: UsageRecord) -> bool:
    return any(_usage(rec))


async def _load(session: AsyncSession, column, value: str) -> list[UsageRecord]:
    rows = await session.execute(select(UsageRecord).where(column == value))
    return list(rows.scalars().all())


async def aggregate_entity(session: AsyncSession, entity_id: str) -> dict:
    """按节点/类别聚合单个 entity(episode 或 script)的估算成本。"""
    by_node: dict[str, float] = {}
    by_kind: dict[str, float] = {}
    total = 0.0
    tokens_total = 0
    unpriced = False
    cache: dict[str, Cost | None] = {}

    for r in await _load(session, UsageRecord.entity_id, entity_id):
        amt, priced = estimate_one(r, _cost_of(r.model, cache))
        if not priced and _has_usage(r):
            unpriced = True
        by_node[r.node] = round(by_node.get(r.node, 0.0) + amt, 4)
        by_kind[r.kind] = round(by_kind.get(r.kind, 0.0) + amt, 4)
        total = round(total + amt, 4)
        in_tok, out_tok, _s, _c = _usage(r)
        tokens_total += in_tok + out_tok

    return {
        "by_node": by_node,
        "by_kind": by_kind,
        "total": total,
        "tokens_total": tokens_total,
        "unpriced": unpriced,
    }


async def project_total(session: AsyncSession, project_id: str) -> dict:
    """整个项目(全 entity)的估算成本合计。"""
    total = 0.0
    unpriced = False
    cache: dict[str, Cost | None] = {}

    for r in await _load(session, UsageRecord.project_id, project_id):
        amt, priced = estimate_one(r, _cost_of(r.model, cache))
        if not priced and _has_usage(r):
            unpriced = True
        total = round(total + amt, 4)

    return {"total": total, "unpriced": unpriced}
