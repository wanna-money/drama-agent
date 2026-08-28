import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.mark.asyncio
async def test_create_seeds_screenplay_versions_when_seed_given():
    """建集时给 seed_screenplay → 种进 screenplay_versions(改编切片直接成为集的初始剧本)。"""
    from drama_agent.db.models import Base, Project, Episode
    from drama_agent.services import episode_service
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(Project(id="p", title="t", genre="drama"))
        await s.commit()
        ep = await episode_service.create(
            s, project_id="p", title="第1集", script_id=None,
            llm_model="m", video_provider="seedance", video_model="", resolution="768P",
            seed_screenplay="第一集切片正文")
        row = (await s.execute(select(Episode).where(Episode.id == ep["id"]))).scalar_one()
    assert row.screenplay_versions[0]["screenplay"] == "第一集切片正文"
    assert row.screenplay_versions[0]["label"] == "分集剧本"
    assert row.screenplay_version_current == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_without_seed_leaves_versions_unseeded():
    """不传 seed(从故事/复用剧本)→ 不种版本,不误触发'直达分镜'。"""
    from drama_agent.db.models import Base, Project, Episode
    from drama_agent.services import episode_service
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(Project(id="p", title="t", genre="drama"))
        await s.commit()
        ep = await episode_service.create(
            s, project_id="p", title="第1集", script_id=None,
            llm_model="m", video_provider="seedance", video_model="", resolution="768P")
        row = (await s.execute(select(Episode).where(Episode.id == ep["id"]))).scalar_one()
    assert not row.screenplay_versions       # None 或 []
    await engine.dispose()
