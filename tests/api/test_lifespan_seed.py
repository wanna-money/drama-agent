"""lifespan 启动时先 seed 内置 provider,rebuild 后 registry 能解析内置 model。"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def db():
    import drama_agent.db.session as db_session
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_session.AsyncSessionLocal
    db_session.AsyncSessionLocal = factory
    yield factory
    db_session.AsyncSessionLocal = orig
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_then_rebuild_registry_resolves_builtin(db):
    """seed → rebuild 后,registry 能从 DB 解析出内置 model(DeepSeek)。"""
    import drama_agent.provider as provider_pkg
    from drama_agent.provider.seed import seed_providers
    from drama_agent.provider import rebuild_registry

    inserted = await seed_providers()
    assert inserted >= 1
    reg = await rebuild_registry()
    prov, model = reg.resolve_model("deepseek-v4-pro")
    assert prov.id == "drama"
    assert model.id == "deepseek-v4-pro"

    # 恢复全局单例,避免污染其他测试
    provider_pkg.provider_registry = provider_pkg.build_registry()
