"""seed_providers: 内置声明幂等写入 DB + 首次导入 env key。"""
import pytest
from sqlalchemy import select
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
async def test_seed_inserts_builtins_with_builtin_flag(db):
    from drama_agent.provider.seed import seed_providers
    from drama_agent.db.models import CustomProvider

    inserted = await seed_providers()
    assert inserted >= 1  # 至少内置 DeepSeek(drama)

    async with db() as s:
        rows = (await s.execute(select(CustomProvider))).scalars().all()
    ids = {r.provider_id for r in rows}
    assert "drama" in ids  # 内置文本模型只保留 DeepSeek
    assert all(r.builtin is True for r in rows)


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_preserves_user_edits(db):
    from drama_agent.provider.seed import seed_providers
    from drama_agent.db.models import CustomProvider

    await seed_providers()
    # 模拟用户改了 drama 的 api_key
    async with db() as s:
        row = (await s.execute(
            select(CustomProvider).where(CustomProvider.provider_id == "drama")
        )).scalar_one()
        row.api_key = "sk-user-edited"
        await s.commit()

    # 再 seed:不新增、不覆盖用户改过的值
    inserted2 = await seed_providers()
    assert inserted2 == 0
    async with db() as s:
        row = (await s.execute(
            select(CustomProvider).where(CustomProvider.provider_id == "drama")
        )).scalar_one()
        assert row.api_key == "sk-user-edited"


@pytest.mark.asyncio
async def test_seed_imports_env_key_on_first_insert(db, monkeypatch):
    """首次插入时 api_key 取 provider.resolve_credential()(settings 现值)。"""
    import drama_agent.provider.llm.providers as llm_providers
    monkeypatch.setattr(llm_providers.settings, "drama_api_key", "sk-from-env")
    from drama_agent.provider.seed import seed_providers
    from drama_agent.db.models import CustomProvider

    await seed_providers()
    async with db() as s:
        row = (await s.execute(
            select(CustomProvider).where(CustomProvider.provider_id == "drama")
        )).scalar_one()
    assert row.api_key == "sk-from-env"


@pytest.mark.asyncio
async def test_seed_inserts_image_builtins(db):
    """内置图片模型:doubao-image 启用、openai-image(gpt-image-2)预留禁用。"""
    from drama_agent.provider.seed import seed_providers
    from drama_agent.db.models import CustomProvider
    await seed_providers()
    async with db() as s:
        rows = {r.provider_id: r for r in (await s.execute(select(CustomProvider))).scalars().all()}
    assert "doubao-image" in rows
    assert rows["doubao-image"].kind == "image" and rows["doubao-image"].enabled is True
    assert "openai-image" in rows and rows["openai-image"].enabled is False
