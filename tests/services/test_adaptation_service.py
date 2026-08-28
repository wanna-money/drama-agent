import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


async def _factory():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_project(factory, **cols):
    from drama_agent.db.models import Project
    async with factory() as s:
        s.add(Project(id="p", title="小说作品", genre="drama",
                      source_text="很长的小说正文", **cols))
        await s.commit()


def _llm(ret):
    """mock LLM + 默认模型解析(禁止真调外部)。"""
    return (
        patch("drama_agent.services.llm_service.llm_service.complete_json",
              new_callable=AsyncMock, return_value=ret),
        patch("drama_agent.provider.provider_registry.effective_default", return_value=None),
    )


def _llm_raises(exc):
    """同 _llm,但让 LLM 调用抛异常(模拟传输层故障)。"""
    return (
        patch("drama_agent.services.llm_service.llm_service.complete_json",
              new_callable=AsyncMock, side_effect=exc),
        patch("drama_agent.provider.provider_registry.effective_default", return_value=None),
    )


@pytest.mark.asyncio
async def test_adapt_writes_draft_and_marks_draft_ready():
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=2)
    m1, m2 = _llm([
        {"index": 1, "title": "第 1 集 · 启程", "screenplay": "第一集正文"},
        {"index": 2, "title": "第 2 集 · 遇险", "screenplay": "第二集正文"},
    ])
    with m1, m2:
        async with factory() as s:
            await adaptation_service.adapt(s, "p")
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "draft_ready"
    assert [d["screenplay"] for d in p.adapted_draft] == ["第一集正文", "第二集正文"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_adapt_coerces_missing_title_and_drops_item_without_screenplay():
    """个别段畸形:缺 title→默认'第 N 集';缺 screenplay→丢弃。不因一段坏而整份失败。"""
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=3)
    m1, m2 = _llm([
        {"index": 1, "screenplay": "有正文没标题"},
        {"index": 2, "title": "只有标题"},              # 无 screenplay → 丢
        {"index": 3, "title": "第三集", "screenplay": "第三集正文"},
    ])
    with m1, m2:
        async with factory() as s:
            await adaptation_service.adapt(s, "p")
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "draft_ready"
    assert len(p.adapted_draft) == 2
    assert p.adapted_draft[0]["title"] == "第 1 集"       # 缺 title 的默认
    assert [d["index"] for d in p.adapted_draft] == [1, 2]  # index 重排连续
    await engine.dispose()


@pytest.mark.asyncio
async def test_adapt_marks_failed_when_whole_output_unusable():
    """整份不可解析/空 → failed(不把空当成功)。"""
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=2)
    m1, m2 = _llm({"error": "模型没按格式返回"})
    with m1, m2:
        async with factory() as s:
            await adaptation_service.adapt(s, "p")
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "failed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_adapt_tolerates_episode_count_mismatch():
    """请求 5 集、模型给 3 段:不硬失败,原样入草稿交人工在预览步调整。"""
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=5)
    m1, m2 = _llm([{"index": i, "title": f"第{i}集", "screenplay": f"正文{i}"} for i in (1, 2, 3)])
    with m1, m2:
        async with factory() as s:
            await adaptation_service.adapt(s, "p")
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "draft_ready"
    assert len(p.adapted_draft) == 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_adapt_reraises_llm_transport_error_without_marking_failed():
    """传输层异常(超时/429/5xx)必须向上抛给 job 重试,**不能**被吞成 failed。

    若日后有人给 complete_json 包一层 `try/except → failed`,可重试的瞬时故障
    就会被永久标记失败(作品再也跑不起来),且现有测试全绿无人拦截。
    """
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=2, adaptation_status="adapting")
    m1, m2 = _llm_raises(RuntimeError("LLM 超时"))
    with m1, m2:
        async with factory() as s:
            with pytest.raises(RuntimeError):
                await adaptation_service.adapt(s, "p")
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert p.adaptation_status == "adapting"      # 未被吞成 failed → 仍可重试
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_draft_only_when_draft_ready():
    """草稿仅 draft_ready 可改(覆盖=幂等);其它状态返回 None 交接口转 409。"""
    from drama_agent.db.models import Project
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed_project(factory, target_episodes=1,
                        adaptation_status="draft_ready",
                        adapted_draft=[{"index": 1, "title": "旧", "screenplay": "旧正文"}])
    new = [{"index": 1, "title": "新", "screenplay": "新正文"}]
    async with factory() as s:
        assert await adaptation_service.save_draft(s, "p", new) is not None
    async with factory() as s:
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
        assert p.adapted_draft[0]["screenplay"] == "新正文"
        p.adaptation_status = "committed"
        await s.commit()
    async with factory() as s:
        assert await adaptation_service.save_draft(s, "p", new) is None   # 已建集 → 不许再改
    await engine.dispose()
