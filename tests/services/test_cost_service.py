"""cost_service: 用量 × 当前 Cost 单价的估算与聚合。

resolve_model 真实签名为 ProviderRegistry 方法,返回 (Provider, Model),
未知 model 抛 ValueError(不返回 None)—— 未定价路径靠捕获该异常,故此处按
既有约定 patch registry 单例的方法。
"""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
    await eng.dispose()


def _model(model_id: str, cost):
    from drama_agent.provider.base import Model
    return Model(id=model_id, label=model_id, provider="p", kind="llm", cost=cost)


def _registry(resolve):
    reg = MagicMock()
    reg.resolve_model = MagicMock(side_effect=resolve)
    return reg


def test_estimate_one_llm_tokens_per_million():
    from drama_agent.db.models import UsageRecord
    from drama_agent.provider.base import Cost
    from drama_agent.services import cost_service

    rec = UsageRecord(id="1", entity_id="e", project_id="p", kind="llm", model="m",
                      input_tokens=1_000_000, output_tokens=500_000, calls=1)
    amt, priced = cost_service.estimate_one(rec, Cost(input=2.0, output=8.0))
    assert priced is True
    assert amt == 6.0  # 1M*2 + 0.5M*8


def test_estimate_one_video_seconds_and_unpriced():
    from drama_agent.db.models import UsageRecord
    from drama_agent.provider.base import Cost
    from drama_agent.services import cost_service

    rec = UsageRecord(id="2", entity_id="e", project_id="p", kind="video", model="v",
                      video_seconds=5, calls=1)
    assert cost_service.estimate_one(rec, Cost(per_second=0.5)) == (2.5, True)
    assert cost_service.estimate_one(rec, None) == (0.0, False)


@pytest.mark.asyncio
async def test_aggregate_entity_by_node(session):
    from drama_agent.db.models import UsageRecord
    from drama_agent.provider.base import Cost
    from drama_agent.services import cost_service

    session.add_all([
        UsageRecord(id="a", entity_id="e1", project_id="p1", node="screenplay_writer",
                    kind="llm", model="m", input_tokens=1_000_000, output_tokens=0, calls=1),
        UsageRecord(id="b", entity_id="e1", project_id="p1", node="video_generator",
                    kind="video", model="v", video_seconds=10, calls=1),
    ])
    await session.commit()

    def resolve(model, provider_hint=None):
        cost = Cost(input=3.0) if model == "m" else Cost(per_second=0.5)
        return MagicMock(), _model(model, cost)

    with patch("drama_agent.provider.provider_registry", _registry(resolve)):
        agg = await cost_service.aggregate_entity(session, "e1")

    assert agg["by_node"]["screenplay_writer"] == 3.0
    assert agg["by_node"]["video_generator"] == 5.0
    assert agg["by_kind"] == {"llm": 3.0, "video": 5.0}
    assert agg["total"] == 8.0
    assert agg["tokens_total"] == 1_000_000
    assert agg["unpriced"] is False


@pytest.mark.asyncio
async def test_aggregate_marks_unpriced_on_unknown_model(session):
    """未知 model → resolve_model 抛 ValueError,须记未定价而非炸掉聚合。"""
    from drama_agent.db.models import UsageRecord
    from drama_agent.services import cost_service

    session.add(UsageRecord(id="c", entity_id="e2", project_id="p1", node="n",
                            kind="llm", model="unknown", input_tokens=100, calls=1))
    await session.commit()

    def resolve(model, provider_hint=None):
        raise ValueError(f"Unknown model: {model!r}")

    with patch("drama_agent.provider.provider_registry", _registry(resolve)):
        agg = await cost_service.aggregate_entity(session, "e2")

    assert agg["unpriced"] is True
    assert agg["total"] == 0.0


@pytest.mark.asyncio
async def test_project_total_spans_entities_and_resolves_once_per_model(session):
    from drama_agent.db.models import UsageRecord
    from drama_agent.provider.base import Cost
    from drama_agent.services import cost_service

    session.add_all([
        UsageRecord(id="d", entity_id="e1", project_id="p1", node="n", kind="llm",
                    model="m", input_tokens=1_000_000, calls=1),
        UsageRecord(id="e", entity_id="e2", project_id="p1", node="n", kind="llm",
                    model="m", input_tokens=1_000_000, calls=1),
        UsageRecord(id="f", entity_id="e3", project_id="other", node="n", kind="llm",
                    model="m", input_tokens=1_000_000, calls=1),
    ])
    await session.commit()

    reg = _registry(lambda model, provider_hint=None: (MagicMock(), _model(model, Cost(input=3.0))))
    with patch("drama_agent.provider.provider_registry", reg):
        agg = await cost_service.project_total(session, "p1")

    assert agg["total"] == 6.0  # 只算 p1 的两条
    assert agg["unpriced"] is False
    assert reg.resolve_model.call_count == 1  # 同 model 只解析一次
