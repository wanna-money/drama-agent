import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


async def _factory():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


DRAFT = [
    {"index": 1, "title": "第 1 集", "screenplay": "第一集正文"},
    {"index": 2, "title": "第 2 集", "screenplay": "第二集正文"},
]


async def _seed(factory, **cols):
    from drama_agent.db.models import Project
    async with factory() as s:
        s.add(Project(id="p", title="小说作品", genre="drama", source_text="正文",
                      adapted_draft=DRAFT, adaptation_status="draft_ready", **cols))
        await s.commit()


@pytest.mark.asyncio
async def test_commit_creates_one_episode_per_draft_item_with_seeded_screenplay():
    from drama_agent.db.models import Project, Episode
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed(factory, target_seconds_per_episode=90)
    async with factory() as s:
        created = await adaptation_service.commit(
            s, "p", llm_model="m", video_provider="seedance", resolution="768P")
    assert len(created) == 2
    async with factory() as s:
        eps = (await s.execute(
            select(Episode).where(Episode.project_id == "p")
            .order_by(Episode.episode_number))).scalars().all()
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert [e.episode_number for e in eps] == [1, 2]
    assert eps[0].screenplay_versions[0]["screenplay"] == "第一集正文"
    assert eps[0].target_seconds == 90              # 时长模式:每集用该值
    assert p.adaptation_status == "committed"
    await engine.dispose()


@pytest.mark.asyncio
async def test_commit_is_atomic_no_half_season_on_failure():
    """建到第 2 集时失败 → 整体回滚:一集都不留,状态仍 draft_ready。

    原先靠"预占 episode_number=2 让第二次创建撞 UNIQUE"来制造失败,但集号现在由
    create 自动避让(改编不再硬用草稿 index),那条碰撞路径已不可达 —— 于是改为直接
    让第二次 create 抛错。被守的性质不变:中途失败不留半个季。
    """
    from unittest.mock import patch
    from drama_agent.db.models import Project, Episode
    from drama_agent.services import adaptation_service, episode_service
    engine, factory = await _factory()
    await _seed(factory)
    async with factory() as s:      # 占位集:用于验证回滚后"只剩它"
        s.add(Episode(id="pre", project_id="p", episode_number=2, title="占位",
                      status="created", llm_model="m", video_provider="seedance",
                      video_model="", resolution="768P"))
        await s.commit()
    real_create = episode_service.create
    calls = {"n": 0}

    async def _fail_on_second(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("第 2 集建失败(模拟)")
        return await real_create(*args, **kwargs)

    async with factory() as s:
        with patch.object(episode_service, "create", _fail_on_second):
            with pytest.raises(RuntimeError):
                await adaptation_service.commit(
                    s, "p", llm_model="m", video_provider="seedance", resolution="768P")
    assert calls["n"] == 2              # 确实是在建第 2 集时炸的(而非一上来就炸)
    async with factory() as s:
        n = (await s.execute(select(func.count()).select_from(Episode)
                             .where(Episode.project_id == "p"))).scalar()
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
    assert n == 1                       # 只剩那个占位,新建的一集都没落库
    assert p.adaptation_status == "draft_ready"
    await engine.dispose()


@pytest.mark.asyncio
async def test_commit_rejected_unless_draft_ready():
    """已 committed 再 commit → None(接口转 409),不重复建集。"""
    from drama_agent.services import adaptation_service
    engine, factory = await _factory()
    await _seed(factory)
    async with factory() as s:
        from drama_agent.db.models import Project
        p = (await s.execute(select(Project).where(Project.id == "p"))).scalar_one()
        p.adaptation_status = "committed"
        await s.commit()
    async with factory() as s:
        assert await adaptation_service.commit(
            s, "p", llm_model="m", video_provider="seedance", resolution="768P") is None
    await engine.dispose()
