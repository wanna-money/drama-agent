import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select


@pytest.mark.asyncio
async def test_video_artifact_persist_and_self_reference():
    from drama_agent.db.models import Base, VideoArtifact
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        root = VideoArtifact(
            id="a1", episode_id="e1", project_id="p1", shot_id="s1", parent_id=None,
            provider="minimax", model="MiniMax-H3", resolution="768P", duration=5,
            action="generate", task_id="t1", video_url="http://v1.mp4",
            local_path=None, prompt_text="a hero",
        )
        child = VideoArtifact(
            id="a2", episode_id="e1", project_id="p1", shot_id="s1", parent_id="a1",
            provider="minimax", model="MiniMax-H3", resolution="2K", duration=5,
            action="upscale", task_id="t2", video_url="http://v2.mp4",
            local_path=None, prompt_text="a hero",
        )
        s.add_all([root, child])
        await s.commit()
        rows = (await s.execute(
            select(VideoArtifact).where(VideoArtifact.episode_id == "e1")
        )).scalars().all()
        assert len(rows) == 2
        c = (await s.execute(
            select(VideoArtifact).where(VideoArtifact.id == "a2")
        )).scalar_one()
        assert c.parent_id == "a1"
        assert c.action == "upscale"
    await engine.dispose()
