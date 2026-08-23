import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_script_job_runs_script_graph_and_writes_script():
    import drama_agent.workflow.runner as r
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base, Script
    import uuid
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    sid = str(uuid.uuid4())
    async with db_session.AsyncSessionLocal() as s:
        s.add(Script(id=sid, title="T", source_text="故事", status="queued"))
        await s.commit()

    fake = MagicMock()

    async def _astream(*a, **k):
        yield {
            "story_analysis": {"x": 1}, "screenplay": "剧本正文",
            "current_stage": "screenplay_written",
        }

    fake.astream = _astream
    st = MagicMock()
    st.next = ()
    st.values = {"story_analysis": {"x": 1}, "screenplay": "剧本正文"}
    fake.aget_state = AsyncMock(return_value=st)

    from drama_agent.db.enums import JobKind
    # append_event 不 mock:它是 _persist 里 flush 的 status 变更的唯一提交者(同事务设计)
    with patch.object(r, "get_script_graph", AsyncMock(return_value=fake)):
        await r.run_job({"episode_id": sid, "kind": JobKind.SCRIPT_START.value,
                         "project_id": "", "payload_json": None})
    async with db_session.AsyncSessionLocal() as s:
        row = await s.get(Script, sid)
    assert row.content == "剧本正文" and row.story_analysis == {"x": 1}
    assert row.status == "completed"
    db_session.AsyncSessionLocal = orig
    await eng.dispose()
