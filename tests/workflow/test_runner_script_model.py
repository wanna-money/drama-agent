import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db import session as db_session
from drama_agent.db.enums import LifecycleStatus
from drama_agent.db.models import Base, Script


@pytest.fixture
async def mem_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Local)
    yield Local


async def _mk_script(Local, llm_model):
    sid = str(uuid.uuid4())
    async with Local() as s:
        s.add(Script(id=sid, title="T", genre="drama", source_text="x",
                     status=LifecycleStatus.CREATED.value, llm_model=llm_model))
        await s.commit()
    return sid


@pytest.mark.asyncio
async def test_script_initial_state_uses_stored_llm_model(mem_session):
    from drama_agent.workflow.runner import _build_script_initial_state
    sid = await _mk_script(mem_session, "kimi-k2")
    state = await _build_script_initial_state(sid)
    assert state["llm_model"] == "kimi-k2"


@pytest.mark.asyncio
async def test_script_initial_state_falls_back_when_empty(mem_session, monkeypatch):
    import drama_agent.provider as pp
    from drama_agent.provider.base import Model
    from drama_agent.workflow.runner import _build_script_initial_state
    sid = await _mk_script(mem_session, "")
    fake = type("R", (), {
        "effective_default": lambda self, k: Model(
            id="fallback-llm", label="F", provider="p", kind="llm"),
    })()
    monkeypatch.setattr(pp, "provider_registry", fake)
    state = await _build_script_initial_state(sid)
    assert state["llm_model"] == "fallback-llm"
