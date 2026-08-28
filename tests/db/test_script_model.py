"""Script/Episode 的 schema 契约(合并流水线后)。

拦的是 schema 回退:Script 精简为只读复用素材(无 status/llm_model 等生命周期列);
Episode 承接剧本创作(script_id 可空 + raw_input + target_seconds + 版本树)。
"""
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
async def test_script_is_slim_reusable_material(session):
    """Script 只剩复用素材需要的列 —— 生命周期列已随剧本流程搬到 Episode。"""
    from drama_agent.db.models import Script
    row = Script(id=str(uuid.uuid4()), title="T", source_text="故事", content="正文")
    session.add(row)
    await session.commit()
    await session.refresh(row)
    assert row.content == "正文" and row.project_id is None
    cols = set(Script.__table__.columns.keys())
    # 精简掉的生命周期/版本列不该再存在
    for gone in ("status", "llm_model", "state_snapshot", "screenplay_versions",
                 "screenplay_version_current", "episode_index", "error_message"):
        assert gone not in cols, f"Script 不该再有列 {gone}"


def test_episode_carries_script_creation_columns():
    """Episode 成为唯一制作实体:script_id 可空 + raw_input + target_seconds + 版本树。"""
    from drama_agent.db.models import Episode
    cols = Episode.__table__.columns
    names = set(cols.keys())
    for needed in ("script_id", "raw_input", "target_seconds",
                   "screenplay_versions", "screenplay_version_current"):
        assert needed in names, f"Episode 缺列 {needed}"
    assert cols["script_id"].nullable is True   # 从故事开始时无源剧本
