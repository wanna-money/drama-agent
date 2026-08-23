import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_root_and_get(session):
    from drama_agent.services import artifact_service as svc
    root = await svc.create_root(
        session, episode_id="e1", project_id="p1", shot_id="s1", provider="minimax",
        model="MiniMax-H3", resolution="768P", duration=5, task_id="t1",
        video_url="http://v.mp4", local_path=None, prompt_text="hero",
    )
    assert root["parent_id"] is None
    assert root["action"] == "generate"
    assert "id" in root and "created_at" in root
    got = await svc.get(session, root["id"])
    assert got["id"] == root["id"]


@pytest.mark.asyncio
async def test_create_child_links_parent(session):
    from drama_agent.services import artifact_service as svc
    root = await svc.create_root(
        session, episode_id="e1", project_id="p1", shot_id="s1", provider="minimax", model="",
        resolution="768P", duration=5, task_id="t1", video_url="http://v.mp4",
        local_path=None, prompt_text="hero",
    )
    child = await svc.create_child(session, root, {
        "episode_id": "e1", "project_id": "p1", "shot_id": "s1", "parent_id": root["id"],
        "provider": "minimax", "model": "", "resolution": "2K", "duration": 5,
        "action": "upscale", "task_id": "t2", "video_url": "http://2k.mp4",
        "local_path": None, "prompt_text": "hero",
    })
    assert child["parent_id"] == root["id"]
    tree = await svc.list_by_shot(session, "e1", "s1")
    assert len(tree) == 2


@pytest.mark.asyncio
async def test_list_by_shot_scoped(session):
    from drama_agent.services import artifact_service as svc
    await svc.create_root(session, episode_id="e1", project_id="p1", shot_id="s1", provider="seedance",
                          model="", resolution="1080p", duration=5, task_id="t",
                          video_url="u", local_path=None, prompt_text="x")
    await svc.create_root(session, episode_id="e1", project_id="p1", shot_id="s2", provider="seedance",
                          model="", resolution="1080p", duration=5, task_id="t",
                          video_url="u", local_path=None, prompt_text="x")
    assert len(await svc.list_by_shot(session, "e1", "s1")) == 1


@pytest.mark.asyncio
async def test_list_by_shot_scoped_per_episode(session):
    """同 shot_id 在不同集互不串(shot_id 唯一性收敛到集内)。"""
    from drama_agent.services import artifact_service as svc
    await svc.create_root(session, episode_id="epA", project_id="p1", shot_id="s1", provider="seedance",
                          model="", resolution="1080p", duration=5, task_id="t",
                          video_url="u", local_path=None, prompt_text="x")
    await svc.create_root(session, episode_id="epB", project_id="p1", shot_id="s1", provider="seedance",
                          model="", resolution="1080p", duration=5, task_id="t",
                          video_url="u", local_path=None, prompt_text="x")
    assert len(await svc.list_by_shot(session, "epA", "s1")) == 1  # 只 epA 的那条
