import uuid
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
async def test_usage_record_defaults(session):
    from drama_agent.db.models import UsageRecord
    from drama_agent.db.enums import UsageKind
    row = UsageRecord(id=str(uuid.uuid4()), entity_id="e1", project_id="p1",
                      kind=UsageKind.LLM.value, model="m", input_tokens=100, output_tokens=50)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    assert row.video_seconds == 0 and row.calls == 1 and row.is_script is False
    assert row.input_tokens == 100 and row.output_tokens == 50 and row.kind == "llm"
