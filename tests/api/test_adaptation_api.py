"""作品级「小说改编 → 分集切分」端点。

重点覆盖状态守卫与幂等(规范 3):每个写接口都不许在错误状态下产生副作用,
重复调用不许双建集 / 双入队。
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest_asyncio.fixture
async def client(monkeypatch):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    from drama_agent.main import app
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(db_session, "AsyncSessionLocal", factory)

    async def _get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[db_session.get_db] = _get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


async def _make_project(client, **body):
    r = await client.post("/api/projects", json={"title": "小说作品", "genre": "drama", **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _set_draft_state(project_id: str, status, draft=None):
    """直接把作品置成某个改编状态(模拟改编 job 已跑完),绕开 LLM。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project
    async with db_session.AsyncSessionLocal() as s:
        p = (await s.execute(select(Project).where(Project.id == project_id))).scalar_one()
        p.adaptation_status = status.value
        p.adapted_draft = draft
        await s.commit()


async def _read_project(project_id: str):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project
    async with db_session.AsyncSessionLocal() as s:
        return (await s.execute(select(Project).where(Project.id == project_id))).scalar_one()


@pytest.mark.asyncio
async def test_create_project_rejects_ambiguous_split_config(client):
    """有小说正文时,切分依据必须恰好二选一(都给/都不给都是 422)。"""
    both = await client.post("/api/projects", json={
        "title": "x", "source_text": "正文", "target_episodes": 5,
        "target_seconds_per_episode": 90})
    neither = await client.post("/api/projects", json={"title": "x", "source_text": "正文"})
    assert both.status_code == 422
    assert neither.status_code == 422


@pytest.mark.asyncio
async def test_adapt_enqueues_job_and_is_idempotent_on_double_click(client):
    from drama_agent.db.models import Job
    import drama_agent.db.session as db_session
    pid = await _make_project(client, source_text="正文", target_episodes=3)
    r1 = await client.post(f"/api/projects/{pid}/adapt")
    assert r1.status_code == 200
    assert r1.json()["adaptation_status"] == "adapting"
    r2 = await client.post(f"/api/projects/{pid}/adapt")     # 双击:已在 adapting → 409
    assert r2.status_code == 409
    async with db_session.AsyncSessionLocal() as s:
        jobs = (await s.execute(select(Job).where(Job.episode_id == pid))).scalars().all()
    assert len(jobs) == 1                                     # 只入队一条
    # 入队与置 adapting 必须同事务落库:否则会留下「有 ADAPT job、作品却仍是 none」的
    # 错位(界面显示未改编,后台已在跑)。job 与状态一起从 DB 读回来验。
    from drama_agent.db.enums import AdaptationStatus
    p = await _read_project(pid)
    assert p.adaptation_status == AdaptationStatus.ADAPTING.value


@pytest.mark.asyncio
async def test_adapt_rejected_without_source_text(client):
    pid = await _make_project(client)
    r = await client.post(f"/api/projects/{pid}/adapt")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_draft_and_commit_guards(client):
    """草稿/建集都只在 draft_ready 放行;commit 后再 commit → 409(不双建)。"""
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project, Episode
    pid = await _make_project(client, source_text="正文", target_episodes=2)
    draft = [{"index": 1, "title": "第 1 集", "screenplay": "正文一"},
             {"index": 2, "title": "第 2 集", "screenplay": "正文二"}]

    # 还没改编(none)→ 改草稿/建集都不行
    assert (await client.put(f"/api/projects/{pid}/adaptation/draft",
                             json={"draft": draft})).status_code == 409
    assert (await client.post(f"/api/projects/{pid}/adaptation/commit",
                              json={})).status_code == 409

    # 手工置成 draft_ready(模拟改编完成)
    async with db_session.AsyncSessionLocal() as s:
        p = (await s.execute(select(Project).where(Project.id == pid))).scalar_one()
        p.adaptation_status = "draft_ready"
        p.adapted_draft = draft
        await s.commit()

    assert (await client.put(f"/api/projects/{pid}/adaptation/draft",
                             json={"draft": draft})).status_code == 200
    got = (await client.get(f"/api/projects/{pid}/adaptation")).json()
    assert got["adaptation_status"] == "draft_ready" and len(got["adapted_draft"]) == 2

    r = await client.post(f"/api/projects/{pid}/adaptation/commit", json={})
    assert r.status_code == 200 and len(r.json()["episodes"]) == 2
    async with db_session.AsyncSessionLocal() as s:
        eps = (await s.execute(select(Episode).where(Episode.project_id == pid))).scalars().all()
    assert len(eps) == 2
    # 再 commit 一次:不许双建
    assert (await client.post(f"/api/projects/{pid}/adaptation/commit",
                              json={})).status_code == 409


@pytest.mark.asyncio
async def test_draft_rejects_item_without_screenplay(client):
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Project
    pid = await _make_project(client, source_text="正文", target_episodes=1)
    async with db_session.AsyncSessionLocal() as s:
        p = (await s.execute(select(Project).where(Project.id == pid))).scalar_one()
        p.adaptation_status = "draft_ready"
        await s.commit()
    r = await client.put(f"/api/projects/{pid}/adaptation/draft",
                         json={"draft": [{"index": 1, "title": "空集", "screenplay": "  "}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_commit_rejects_empty_draft_and_leaves_project_recoverable(client):
    """空草稿建集 → 422,且不得置 committed。

    放行的话会「建 0 集却置 committed」:committed 既不能再 commit(409)也不能
    重新改编(409)→ 作品零集且无路可走,只能删库重建。
    """
    from drama_agent.db.enums import AdaptationStatus
    from drama_agent.db.models import Episode
    import drama_agent.db.session as db_session
    pid = await _make_project(client, source_text="正文", target_episodes=1)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=[])

    r = await client.post(f"/api/projects/{pid}/adaptation/commit", json={})
    assert r.status_code == 422

    p = await _read_project(pid)
    assert p.adaptation_status == AdaptationStatus.DRAFT_READY.value   # 没被锁死
    async with db_session.AsyncSessionLocal() as s:
        eps = (await s.execute(select(Episode).where(Episode.project_id == pid))).scalars().all()
    assert eps == []


@pytest.mark.asyncio
async def test_draft_rejects_malformed_items_without_wiping_stored_draft(client):
    """入参非空但每项畸形(缺剧本正文)→ 422,且库里既有草稿不被静默清空。

    save_draft 内部会规整草稿并丢弃无正文的段;若这类入参被放行,用户的草稿会被
    规整成 [] 写回、接口却回 200 —— 草稿被静默清空。
    """
    from drama_agent.db.enums import AdaptationStatus
    stored = [{"index": 1, "title": "第 1 集", "screenplay": "正文一"}]
    pid = await _make_project(client, source_text="正文", target_episodes=1)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=stored)

    r = await client.put(f"/api/projects/{pid}/adaptation/draft",
                         json={"draft": [{"index": 1, "title": "无正文"}]})
    assert r.status_code == 422

    p = await _read_project(pid)
    assert p.adapted_draft == stored                                   # 原草稿还在
    assert p.adaptation_status == AdaptationStatus.DRAFT_READY.value


@pytest.mark.asyncio
async def test_adapt_rejected_after_commit(client):
    """已建集(committed)后不许重新改编 → 409。

    放行会走到「新草稿 + 再 commit」,而各集 episode_number 从 1 重排 →
    撞 uq_episode_number 唯一约束。
    """
    from drama_agent.db.enums import AdaptationStatus
    pid = await _make_project(client, source_text="正文", target_episodes=2)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=[
        {"index": 1, "title": "第 1 集", "screenplay": "正文一"},
        {"index": 2, "title": "第 2 集", "screenplay": "正文二"}])
    assert (await client.post(f"/api/projects/{pid}/adaptation/commit",
                              json={})).status_code == 200

    assert (await client.post(f"/api/projects/{pid}/adapt")).status_code == 409
    p = await _read_project(pid)
    assert p.adaptation_status == AdaptationStatus.COMMITTED.value     # 未被拉回 adapting


@pytest.mark.asyncio
async def test_draft_rejects_over_limit_instead_of_silently_truncating(client):
    """超上限的草稿 → 422,而不是静默截断到 MAX_DRAFT_EPISODES 还回 200。

    规整逻辑会 `raw[:MAX_DRAFT_EPISODES]`,放行 = 用户多出来的集被悄悄丢掉。
    """
    from drama_agent.db.enums import AdaptationStatus
    from drama_agent.services.adaptation_service import MAX_DRAFT_EPISODES
    stored = [{"index": 1, "title": "第 1 集", "screenplay": "正文一"}]
    pid = await _make_project(client, source_text="正文", target_episodes=1)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=stored)

    over = [{"index": i + 1, "title": f"第 {i + 1} 集", "screenplay": f"正文{i}"}
            for i in range(MAX_DRAFT_EPISODES + 50)]
    r = await client.put(f"/api/projects/{pid}/adaptation/draft", json={"draft": over})
    assert r.status_code == 422

    p = await _read_project(pid)
    assert p.adapted_draft == stored                                   # 原草稿未被覆盖


@pytest.mark.asyncio
async def test_commit_avoids_existing_episode_numbers(client):
    """作品已有手建的集时,建集要绕开已占用的集号,而不是撞 uq_episode_number。

    「新建一集」按钮在作品页始终可见,用户完全可能先手建一集再去用小说改编。
    用草稿 index 硬指定集号会 IntegrityError → 500,且该作品永远建不出集。
    """
    from drama_agent.db.enums import AdaptationStatus
    from drama_agent.db.models import Episode
    import drama_agent.db.session as db_session
    pid = await _make_project(client, source_text="正文", target_episodes=2)
    manual = await client.post(f"/api/projects/{pid}/episodes",
                               json={"title": "手建的一集", "raw_input": "手写的故事"})
    assert manual.status_code == 200, manual.text
    assert manual.json()["episode_number"] == 1

    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=[
        {"index": 1, "title": "改编 1", "screenplay": "正文一"},
        {"index": 2, "title": "改编 2", "screenplay": "正文二"}])
    r = await client.post(f"/api/projects/{pid}/adaptation/commit", json={})
    assert r.status_code == 200, r.text

    async with db_session.AsyncSessionLocal() as s:
        eps = (await s.execute(select(Episode).where(Episode.project_id == pid))).scalars().all()
    nums = sorted(e.episode_number for e in eps)
    assert nums == [1, 2, 3]                       # 手建的 1 仍在,改编的两集接在后面
    assert len(nums) == len(set(nums))             # 集号不重复
    titles = {e.title for e in eps}
    assert "手建的一集" in titles                    # 原有集没被顶掉
    assert {"改编 1", "改编 2"} <= titles


@pytest.mark.asyncio
async def test_adapt_response_never_lies_when_job_already_queued(client):
    """已有同 dedup_key 的 ADAPT job 处于 RUNNING 时,响应不得与 DB 状态脱节。

    该窗口真实存在:adapt 服务内部先把 draft_ready commit 了,worker 事后才另开
    session 标 succeeded —— 期间 project=draft_ready 而 job 仍 RUNNING,/adapt 的
    守卫(只拦 adapting/committed)会放行。若入队走早返回分支而不落库,就会出现
    「响应说 adapting、DB 仍是 draft_ready」:界面显示改编中,却没有任何任务在跑。
    """
    import uuid
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Job
    from drama_agent.db.enums import AdaptationStatus, JobKind, JobStatus
    pid = await _make_project(client, source_text="正文", target_episodes=2)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=[
        {"index": 1, "title": "第 1 集", "screenplay": "正文一"}])
    async with db_session.AsyncSessionLocal() as s:
        s.add(Job(id=str(uuid.uuid4()), episode_id=pid, project_id=pid,
                  kind=JobKind.ADAPT.value, status=JobStatus.RUNNING.value,
                  dedup_key="adapt"))
        await s.commit()

    r = await client.post(f"/api/projects/{pid}/adapt")
    assert r.status_code == 200

    p = await _read_project(pid)
    assert p.adaptation_status == r.json()["adaptation_status"], (
        f"响应说 {r.json()['adaptation_status']!r},DB 却是 {p.adaptation_status!r}")
    async with db_session.AsyncSessionLocal() as s:
        jobs = (await s.execute(select(Job).where(Job.episode_id == pid))).scalars().all()
    assert len(jobs) == 1                                              # 仍然去重,不新建


@pytest.mark.asyncio
async def test_put_draft_returns_same_shape_as_get(client):
    """PUT 的响应形状必须与 GET 完全一致(契约:PUT → 同 GET 形状)。

    少一个键前端就会踩空:前端把 PUT 结果直接 setState,若 source_text 丢了会变成
    undefined → 命中"非小说作品不显示本面板"的判断 → 保存成功却整块面板消失。
    """
    from drama_agent.db.enums import AdaptationStatus
    draft = [{"index": 1, "title": "第 1 集", "screenplay": "正文一"}]
    pid = await _make_project(client, source_text="小说正文", target_episodes=1)
    await _set_draft_state(pid, AdaptationStatus.DRAFT_READY, draft=draft)

    got = await client.get(f"/api/projects/{pid}/adaptation")
    put = await client.put(f"/api/projects/{pid}/adaptation/draft", json={"draft": draft})
    assert put.status_code == 200

    assert put.json().keys() == got.json().keys()
    assert put.json()["source_text"] == got.json()["source_text"] == "小说正文"
    assert put.json()["target_episodes"] == got.json()["target_episodes"] == 1
    # 形状对齐不能以牺牲新鲜度为代价:PUT 回的草稿必须是刚存进去的那份,
    # 而不是保存前的旧值(端点里的 Project 实例取自 save_draft 之前)。
    changed = [{"index": 1, "title": "改过的标题", "screenplay": "改过的正文"}]
    put2 = await client.put(f"/api/projects/{pid}/adaptation/draft", json={"draft": changed})
    assert put2.json()["adapted_draft"] == changed
