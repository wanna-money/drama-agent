import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def db_setup():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base, Project, Episode, Script
    from drama_agent.db.enums import LifecycleStatus
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = factory
    async with factory() as s:
        s.add(Project(id="p1", title="t", genre="drama"))
        # 统一图从有正文的 Script 复用(screenplay_approved),Episode 靠 script_id 关联
        s.add(Script(id="s1", project_id="p1", title="t", source_text="r",
                     content="剧本正文", story_analysis={"genre": "drama"}))
        s.add(Episode(id="e1", project_id="p1", episode_number=1, title="t", script_id="s1",
                      status=LifecycleStatus.QUEUED.value))
        await s.commit()
    yield factory
    db_session.AsyncSessionLocal = orig
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_job_writes_events_and_completes(db_setup):
    from drama_agent.workflow import runner
    from drama_agent.services import event_service as ev
    from drama_agent.db.models import Episode

    async def fake_astream(initial, config, stream_mode):
        for stage in ("story_analyzed", "completed"):
            yield {"current_stage": stage, "title": "t"}

    fake_graph = MagicMock()
    fake_graph.astream = fake_astream
    fake_state = MagicMock()
    fake_state.next = ()          # 无中断 → 完成
    fake_state.values = {"current_stage": "completed", "title": "t"}
    fake_graph.aget_state = AsyncMock(return_value=fake_state)

    with patch("drama_agent.workflow.runner.get_graph", new=AsyncMock(return_value=fake_graph)):
        await runner.run_job({"id": "j1", "episode_id": "e1", "project_id": "p1",
                              "kind": "start", "payload_json": None})

    async with db_setup() as s:
        evts = await ev.fetch_since(s, "e1", 0)
        ep = await s.get(Episode, "e1")
    types = [e["type"] for e in evts]
    assert "stage_change" in types and "completed" in types
    assert ep.status == "completed"


@pytest.mark.asyncio
async def test_run_job_pauses_on_interrupt(db_setup):
    from drama_agent.workflow import runner
    from drama_agent.db.models import Episode

    async def fake_astream(initial, config, stream_mode):
        yield {"current_stage": "screenplay_written", "title": "t"}

    fake_graph = MagicMock()
    fake_graph.astream = fake_astream
    fake_state = MagicMock()
    fake_state.next = ("screenplay_review",)   # 停在中断
    fake_state.values = {"current_stage": "screenplay_written"}
    fake_graph.aget_state = AsyncMock(return_value=fake_state)

    with patch("drama_agent.workflow.runner.get_graph", new=AsyncMock(return_value=fake_graph)):
        await runner.run_job({"id": "j2", "episode_id": "e1", "project_id": "p1",
                              "kind": "start", "payload_json": None})

    async with db_setup() as s:
        ep = await s.get(Episode, "e1")
    assert ep.status == "paused"
    # 中断点写进 snapshot.paused_at,供前端判断停在哪个审核步
    assert ep.state_snapshot.get("paused_at") == "screenplay_review"


def test_summary_covers_every_snapshot_field_the_status_endpoint_reads():
    """/workflow/status 读的是 state_snapshot,而快照由 _summary **整表覆盖**写入。

    _summary 少产出一个字段,该字段在接口上就永远是空 —— look_assignments 正是这么丢的
    (造型审核面板拿到 {})。这里从接口源码里抽出它实际读的键,和 _summary 产出的键对齐,
    以后任何一方加字段而另一方漏了都会立刻被抓到,而不是等界面上发现空白。
    """
    import inspect
    import re
    from drama_agent.api import workflow as wf_api
    from drama_agent.workflow.runner import _summary

    read = set(re.findall(
        r'snapshot\.get\("([^"]+)"', inspect.getsource(wf_api.get_workflow_status)))
    assert read, "没能从 get_workflow_status 里抽到 snapshot.get(...) —— 测试本身失效了"
    produced = set(_summary({}))
    # paused_at 是中断时由 runner 单独补进 payload 的(见 _run_video),不该由 _summary 产出
    missing = read - produced - {"paused_at"}
    assert not missing, f"/workflow/status 会读、但 _summary 不产出的字段: {sorted(missing)}"


@pytest.mark.asyncio
async def test_persist_snapshot_overwrite_does_not_wipe_version_columns(db_setup):
    """剧本版本树在 Episode 专用列上(非 state_snapshot),_persist 整表覆盖 snapshot
    时不能把它抹掉 —— 否则跑一次图,审核阶段存的版本历史就没了。

    这是 Task 4 的本意:版本数据必须挺过一次 graph 事件的 _persist。旧设计里
    versions 存 state_snapshot,会被覆盖;新设计移到专用列,本测试锁死这个隔离。
    """
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Episode
    from drama_agent.db.enums import LifecycleStatus, EventType
    from drama_agent.workflow import runner
    from sqlalchemy import select

    # db_setup 已把 db_session.AsyncSessionLocal patch 成内存库工厂并 seed 了 e1。
    # 用同一个工厂开 session(不要再调 db_setup() —— 那会新建一个独立的引擎/库)。
    factory = db_session.AsyncSessionLocal

    # 先在 e1 上落一份版本历史(模拟审核阶段 append 过)
    async with factory() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == "e1"))).scalar_one()
        ep.screenplay_versions = [{"screenplay": "初稿正文", "label": "初稿"}]
        ep.screenplay_version_current = 0
        await s.commit()

    # 跑一次 _persist(整表覆盖 state_snapshot)。不 mock append_event —— 它负责提交事务,
    # mock 掉就没人 commit,snapshot 写不进库(_persist 只 flush)。真 append_event 顺带写条事件,
    # 在测试库里无害。
    await runner._persist(
        "e1", "p1", LifecycleStatus.RUNNING, EventType.STAGE_CHANGE,
        runner._summary({"current_stage": "storyboard_ready", "title": "t"}),
    )

    async with factory() as s:
        ep = (await s.execute(select(Episode).where(Episode.id == "e1"))).scalar_one()
        assert ep.screenplay_versions == [{"screenplay": "初稿正文", "label": "初稿"}]
        assert ep.screenplay_version_current == 0
        assert ep.state_snapshot["current_stage"] == "storyboard_ready"  # snapshot 确实被覆盖了
