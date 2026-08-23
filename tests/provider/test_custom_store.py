"""P1 tests: CustomProvider 表 + row_to_provider 转换。"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from drama_agent.provider.custom_store import row_to_provider


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_custom_provider_persist_and_convert(session):
    from drama_agent.db.models import CustomProvider
    row = CustomProvider(
        id="c1", provider_id="mycorp", label="私有部署", protocol="openai-compat",
        kind="llm", base_url="https://x/v1", api_key="sk-real-123",
        models_json=[{"id": "qwen-max", "label": "Qwen Max", "provider": "mycorp",
                      "kind": "llm", "context_window": 32768}],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    provider = row_to_provider(row)
    assert provider.id == "mycorp"
    assert provider.protocol == "openai-compat"
    assert provider.base_url == "https://x/v1"
    assert provider.api_key == "sk-real-123"
    assert len(provider.models) == 1
    assert provider.models[0].id == "qwen-max"
    assert provider.models[0].context_window == 32768


def test_row_to_provider_empty_models():
    class FakeRow:
        provider_id = "p"; label = "P"; protocol = "openai-compat"
        base_url = None; api_key = None; models_json = None
    provider = row_to_provider(FakeRow())
    assert provider.models == []
    assert provider.resolve_credential() is None  # 无 key → 未配置


@pytest.mark.asyncio
async def test_custom_provider_builtin_column_defaults_false(session):
    """builtin 列存在且默认 False(界面新建的 provider 默认非内置)。"""
    from drama_agent.db.models import CustomProvider
    row = CustomProvider(
        id="c2", provider_id="acme", label="Acme", protocol="openai-compat",
        kind="llm", base_url=None, api_key=None, models_json=[],
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    assert row.builtin is False

    row2 = CustomProvider(
        id="c3", provider_id="kimi", label="Kimi", protocol="openai-compat",
        kind="llm", api_key="sk-x", models_json=[], builtin=True,
    )
    session.add(row2)
    await session.commit()
    await session.refresh(row2)
    assert row2.builtin is True
