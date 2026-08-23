import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
    await eng.dispose()


@pytest.mark.asyncio
async def test_script_draft_defaults(session):
    import uuid
    from drama_agent.db.models import Script
    from drama_agent.db.enums import LifecycleStatus
    row = Script(id=str(uuid.uuid4()), title="T", source_text="故事")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    assert row.status == LifecycleStatus.CREATED.value
    assert row.content is None and row.project_id is None


def test_episode_has_script_id_not_raw_input():
    from drama_agent.db.models import Episode
    cols = set(Episode.__table__.columns.keys())
    assert "script_id" in cols and "raw_input" not in cols
