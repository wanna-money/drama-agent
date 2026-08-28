"""图入口分流的输入面:`_build_initial_state` 必须和 `graph.route_entry` 用同一判据。

两者一旦分叉就是静默事故:复用剧本的集被当成"从故事开始"重新分析一遍(白烧 LLM、
还会把已审核的正文冲掉),或反过来,从零起的集带着 screenplay_approved=True 跳过写作。
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from drama_agent.db import session as db_session
from drama_agent.db.enums import LifecycleStatus
from drama_agent.db.models import Base, Episode, Script


@pytest.fixture
async def mem_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    Local = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", Local)
    yield Local
    await engine.dispose()


async def _mk_episode(Local, *, script_id: str) -> str:
    eid = str(uuid.uuid4())
    async with Local() as s:
        s.add(Episode(id=eid, project_id="p1", episode_number=1, title="T",
                      script_id=script_id, status=LifecycleStatus.QUEUED.value))
        await s.commit()
    return eid


@pytest.mark.asyncio
async def test_reused_script_state_matches_storyboard_entry(mem_session):
    """有 script_id:带上剧本正文/分析、已审核,且 route_entry 判为直达分镜。"""
    from drama_agent.workflow.graph import route_entry
    from drama_agent.workflow.runner import _build_initial_state

    sid = str(uuid.uuid4())
    async with mem_session() as s:
        s.add(Script(id=sid, project_id="p1", title="T", genre="romance",
                     source_text="原始故事", content="剧本正文",
                     story_analysis={"genre": "thriller"}))
        await s.commit()
    eid = await _mk_episode(mem_session, script_id=sid)

    state = await _build_initial_state(eid)
    assert state["script_id"] == sid
    assert state["screenplay"] == "剧本正文"
    assert state["screenplay_approved"] is True
    assert state["story_analysis"] == {"genre": "thriller"}
    assert state["genre"] == "thriller"        # 分析里的类型优先于剧本上的
    assert route_entry(state) == "storyboard_director"


@pytest.mark.asyncio
async def test_no_script_state_matches_story_entry(mem_session):
    """无 script_id:正文空、未审核,且 route_entry 判为从故事分析开始。"""
    from drama_agent.workflow.graph import route_entry
    from drama_agent.workflow.runner import _build_initial_state

    eid = await _mk_episode(mem_session, script_id="")

    state = await _build_initial_state(eid)
    assert state["screenplay"] == ""
    assert state["screenplay_approved"] is False
    assert state["story_analysis"] is None
    assert route_entry(state) == "story_analyzer"
