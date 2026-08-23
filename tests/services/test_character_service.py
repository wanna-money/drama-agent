import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_then_get(session):
    from drama_agent.services import character_service as cs
    await cs.save(session, "p1", "Alice", "blonde hair, red coat")
    assert await cs.get(session, "p1", "Alice") == "blonde hair, red coat"


@pytest.mark.asyncio
async def test_get_missing_returns_none(session):
    from drama_agent.services import character_service as cs
    assert await cs.get(session, "p1", "Nobody") is None


@pytest.mark.asyncio
async def test_save_upserts_not_duplicates(session):
    from drama_agent.services import character_service as cs
    from drama_agent.db.models import CharacterProfile
    from sqlalchemy import select, func
    await cs.save(session, "p1", "Alice", "v1")
    await cs.save(session, "p1", "Alice", "v2")
    count = (await session.execute(
        select(func.count()).select_from(CharacterProfile)
        .where(CharacterProfile.project_id == "p1", CharacterProfile.name == "Alice")
    )).scalar()
    assert count == 1
    assert await cs.get(session, "p1", "Alice") == "v2"


@pytest.mark.asyncio
async def test_scoped_by_project(session):
    from drama_agent.services import character_service as cs
    await cs.save(session, "p1", "Alice", "a")
    await cs.save(session, "p2", "Alice", "b")
    assert await cs.get(session, "p1", "Alice") == "a"
    assert await cs.get(session, "p2", "Alice") == "b"
