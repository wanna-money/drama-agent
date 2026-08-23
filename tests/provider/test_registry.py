"""Task2 tests: registry 三层合成 + 三跳解析 resolve_model + fallback + available/all 集合。"""
import logging
import pytest
from drama_agent.provider.base import Model, Provider
from drama_agent.provider.registry import ProviderRegistry


def _p(pid, models, api_key=None, base_url=None):
    return Provider(id=pid, label=pid, protocol="openai-compat",
                    api_key=api_key, base_url=base_url, models=models)


def _m(mid, provider, kind="llm"):
    return Model(id=mid, label=mid, provider=provider, kind=kind)


def _reg(builtin=None, custom=None):
    return ProviderRegistry(builtin=builtin or [], custom_providers=custom or [])


# ── resolve_model: 命中 ────────────────────────────────────────────────
def test_resolve_hits_declared_model():
    reg = _reg([_p("kimi", [_m("k2", "kimi")])])
    provider, model = reg.resolve_model("k2")
    assert provider.id == "kimi" and model.id == "k2"


# ── resolve_model: provider 已知、model 未声明 → fallback + warning ────
def test_resolve_unknown_model_builds_fallback(caplog):
    reg = _reg([_p("kimi", [_m("k2", "kimi")])])
    # kimi provider 存在,但要一个未声明的 model id → 需能推断归属 provider
    with caplog.at_level(logging.WARNING):
        provider, model = reg.resolve_model("k2-turbo", provider_hint="kimi")
    assert provider.id == "kimi"
    assert model.id == "k2-turbo"          # 造了个临时 model
    assert any("k2-turbo" in r.message for r in caplog.records)  # 有警告


# ── resolve_model: provider 都不认识 → ValueError ──────────────────────
def test_resolve_unknown_provider_raises():
    reg = _reg([_p("kimi", [_m("k2", "kimi")])])
    with pytest.raises(ValueError):
        reg.resolve_model("totally-unknown")


# ── config custom_providers 覆盖被合入 registry ────────────────────────
def test_custom_provider_from_config_merged():
    builtin = [_p("kimi", [_m("k2", "kimi")])]
    custom = [{
        "id": "mycorp", "label": "私有", "protocol": "openai-compat",
        "base_url": "https://x/v1", "api_key": "$MYCORP_KEY",
        "models": [{"id": "qwen", "label": "Qwen", "provider": "mycorp", "kind": "llm"}],
    }]
    reg = _reg(builtin, custom)
    provider, model = reg.resolve_model("qwen")
    assert provider.id == "mycorp" and model.id == "qwen"


def test_invalid_custom_provider_raises_at_build():
    # 缺 protocol(必填)→ 启动期校验失败,不静默吞
    bad = [{"id": "x", "label": "x"}]  # 无 protocol / models
    with pytest.raises(Exception):
        _reg([], bad)


# ── available vs all:凭证已配的才进 available ──────────────────────────
def test_available_models_filters_by_credential(monkeypatch):
    monkeypatch.setenv("HAVE_KEY", "sk-1")
    monkeypatch.delenv("MISS_KEY", raising=False)
    builtin = [
        _p("has", [_m("m-has", "has")], api_key="$HAVE_KEY"),
        _p("miss", [_m("m-miss", "miss")], api_key="$MISS_KEY"),
    ]
    reg = _reg(builtin)
    all_ids = {m.id for m in reg.models(kind="llm")}
    avail_ids = {m.id for m in reg.models(kind="llm", available_only=True)}
    assert all_ids == {"m-has", "m-miss"}
    assert avail_ids == {"m-has"}          # 未配凭证的 miss 被排除


# ── models(kind=...) 按类别过滤 ────────────────────────────────────────
def test_models_filtered_by_kind():
    builtin = [
        _p("kimi", [_m("k2", "kimi", kind="llm")]),
        _p("seed", [_m("seedance", "seed", kind="video")]),
        _p("img", [_m("sd", "img", kind="image")]),
    ]
    reg = _reg(builtin)
    assert {m.id for m in reg.models(kind="llm")} == {"k2"}
    assert {m.id for m in reg.models(kind="video")} == {"seedance"}
    assert {m.id for m in reg.models(kind="image")} == {"sd"}
    prov, model = reg.resolve_model("sd")
    assert model.kind == "image"


def test_model_is_default_defaults_false_and_roundtrips():
    from drama_agent.provider.base import Model
    m = Model(id="x", label="X", provider="p", kind="llm")
    assert m.is_default is False
    m2 = Model(**{**m.model_dump(), "is_default": True})
    assert m2.is_default is True


def test_registry_converges_multiple_defaults_per_kind():
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="p", label="P", protocol="openai-compat", models=[
        Model(id="a", label="A", provider="p", kind="llm", is_default=True),
        Model(id="b", label="B", provider="p", kind="llm", is_default=True),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    defaults = [m for m in reg.models(kind="llm") if m.is_default]
    assert len(defaults) == 1 and defaults[0].id == "a"


def test_registry_default_model_returns_marked_or_none():
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="p", label="P", protocol="openai-compat", models=[
        Model(id="a", label="A", provider="p", kind="llm"),
        Model(id="b", label="B", provider="p", kind="llm", is_default=True),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    assert reg.default_model("llm").id == "b"
    assert reg.default_model("video") is None


def test_resolve_model_id_with_slash_matches_literal():
    """model id 本身含 '/'(如 jd/x)应按字面匹配,不被误拆成 provider='jd'。"""
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="jdcloud", label="JD", protocol="openai-compat", models=[
        Model(id="jd/deepseek-v4-flash-0731", label="DS", provider="jdcloud", kind="llm"),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    prov, m = reg.resolve_model("jd/deepseek-v4-flash-0731")
    assert prov.id == "jdcloud" and m.id == "jd/deepseek-v4-flash-0731"


def test_effective_default_prefers_is_default():
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="p", label="P", protocol="openai-compat", api_key="k", models=[
        Model(id="a", label="A", provider="p", kind="llm"),
        Model(id="b", label="B", provider="p", kind="llm", is_default=True),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    assert reg.effective_default("llm").id == "b"


def test_effective_default_falls_back_to_first_available():
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="p", label="P", protocol="openai-compat", api_key="k", models=[
        Model(id="a", label="A", provider="p", kind="llm"),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    assert reg.effective_default("llm").id == "a"


def test_available_and_default_exclude_disabled_provider():
    """禁用 provider 即便有凭证也不算"可用":不进 available_only,也不被选成 effective_default。"""
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    disabled = Provider(id="off", label="Off", protocol="openai-compat", api_key="k", enabled=False,
                        models=[Model(id="x", label="X", provider="off", kind="image")])
    on = Provider(id="on", label="On", protocol="openai-compat", api_key="k",
                  models=[Model(id="y", label="Y", provider="on", kind="image")])
    reg = ProviderRegistry(builtin=[disabled, on], custom_providers=[])
    assert {m.id for m in reg.models(kind="image", available_only=True)} == {"y"}
    assert reg.effective_default("image").id == "y"


def test_effective_default_none_when_no_available_and_no_default():
    from drama_agent.provider.base import Model, Provider
    from drama_agent.provider.registry import ProviderRegistry
    p = Provider(id="p", label="P", protocol="openai-compat", models=[  # 无 api_key → 不可用
        Model(id="a", label="A", provider="p", kind="llm"),
    ])
    reg = ProviderRegistry(builtin=[p], custom_providers=[])
    assert reg.effective_default("llm") is None
