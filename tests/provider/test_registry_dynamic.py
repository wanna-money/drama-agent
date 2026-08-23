"""P2 tests: build_registry 合并优先级(DB>env>内置)+ rebuild_registry 重赋值单例。"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

import drama_agent.provider as provider_pkg
from drama_agent.provider.base import Model, Provider


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


def test_build_registry_db_overrides_env(monkeypatch):
    """同 provider_id:DB provider 覆盖 env(DB 优先级最高)。"""
    monkeypatch.setattr(provider_pkg.settings, "custom_providers", [{
        "id": "acme", "label": "ENV版", "protocol": "openai-compat",
        "base_url": "https://env/v1", "api_key": "env-key",
        "models": [{"id": "acme-m", "label": "M", "provider": "acme", "kind": "llm"}],
    }])
    db_provider = Provider(
        id="acme", label="DB版", protocol="openai-compat", base_url="https://db/v1",
        api_key="db-key", models=[Model(id="acme-m", label="M", provider="acme", kind="llm")],
    )
    reg = provider_pkg.build_registry(db_providers=[db_provider])
    p = reg.get_provider("acme")
    assert p.label == "DB版" and p.base_url == "https://db/v1"  # DB 赢


@pytest.mark.asyncio
async def test_rebuild_registry_swaps_singleton_and_reads_db(db):
    from drama_agent.db.models import CustomProvider
    async with db() as s:
        s.add(CustomProvider(
            id="c1", provider_id="fromdb", label="DB Provider", protocol="openai-compat",
            kind="llm", base_url="https://d/v1", api_key="k",
            models_json=[{"id": "db-model", "label": "DB Model", "provider": "fromdb", "kind": "llm"}],
        ))
        await s.commit()

    before = provider_pkg.provider_registry
    reg = await provider_pkg.rebuild_registry()
    # 单例被重赋值
    assert provider_pkg.provider_registry is reg
    assert provider_pkg.provider_registry is not before
    # 新 registry 能解析出 DB 里的 model
    prov, model = reg.resolve_model("db-model")
    assert prov.id == "fromdb" and model.id == "db-model"
    # 重建后恢复(避免污染其他测试的全局单例)
    provider_pkg.provider_registry = provider_pkg.build_registry()


def test_build_registry_without_db_has_no_builtins(monkeypatch):
    """收敛后:不传 db_providers 时 registry 不含任何内置(内置只来自 DB seed)。"""
    import drama_agent.provider as provider_pkg
    # 清空 env override 干扰
    monkeypatch.setattr(provider_pkg.settings, "custom_providers", [])
    reg = provider_pkg.build_registry()  # 无 db_providers
    assert reg.providers() == []  # 内置不再从代码直接进 registry
    provider_pkg.provider_registry = provider_pkg.build_registry()
