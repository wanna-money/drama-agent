"""Task1 tests: resolve_env 值语法 + 目录合并规则(测我们的逻辑,非测 Pydantic)。"""
from drama_agent.provider.base import (
    Model, Provider, resolve_env, merge_providers,
)


# ── resolve_env: $ENV / ${ENV} / 字面 $$ / 未设为 None ──────────────────
def test_resolve_env_bare_ref(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-123")
    assert resolve_env("$MY_KEY") == "sk-123"


def test_resolve_env_braced_ref(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-456")
    assert resolve_env("${MY_KEY}") == "sk-456"


def test_resolve_env_unset_returns_none(monkeypatch):
    monkeypatch.delenv("NOPE_KEY", raising=False)
    assert resolve_env("$NOPE_KEY") is None


def test_resolve_env_literal_dollar_escape():
    # "$$" → 字面 "$",不当成引用
    assert resolve_env("$$literal") == "$literal"


def test_resolve_env_plain_value_passthrough():
    # 不带 $ 的普通值原样返回(明文兜底)
    assert resolve_env("plain-key") == "plain-key"


def test_resolve_env_none_passthrough():
    assert resolve_env(None) is None


# ── merge_providers: 同 id 替换 / 新 id 追加 / 只给 base_url 保留 models ──
def _p(pid, base_url=None, models=None, api_key=None):
    return Provider(id=pid, label=pid, protocol="openai-compat",
                    base_url=base_url, api_key=api_key, models=models or [])


def _m(mid, provider, kind="llm"):
    return Model(id=mid, label=mid, provider=provider, kind=kind)


def test_merge_new_provider_appended():
    builtin = [_p("kimi", models=[_m("k2", "kimi")])]
    override = [_p("mycorp", base_url="https://x/v1", models=[_m("qwen", "mycorp")])]
    result = merge_providers(builtin, override)
    ids = {p.id for p in result}
    assert ids == {"kimi", "mycorp"}


def test_merge_same_provider_field_override():
    builtin = [_p("kimi", base_url="https://old", models=[_m("k2", "kimi")])]
    override = [_p("kimi", base_url="https://new", models=[_m("k2", "kimi")])]
    result = merge_providers(builtin, override)
    kimi = next(p for p in result if p.id == "kimi")
    assert kimi.base_url == "https://new"


def test_merge_base_url_only_keeps_builtin_models():
    # 只给 base_url、不给 models(models 为空)→ 保留内置 models(代理场景)
    builtin = [_p("kimi", base_url="https://old", models=[_m("k2", "kimi")])]
    override = [_p("kimi", base_url="https://proxy")]  # models=[]
    result = merge_providers(builtin, override)
    kimi = next(p for p in result if p.id == "kimi")
    assert kimi.base_url == "https://proxy"
    assert [m.id for m in kimi.models] == ["k2"]  # 内置 model 保留


def test_merge_models_given_replaces_by_id():
    # 同 model id 替换、新 model id 追加
    builtin = [_p("kimi", models=[_m("k2", "kimi"), _m("k1", "kimi")])]
    override = [_p("kimi", models=[_m("k2", "kimi"), _m("k3", "kimi")])]
    result = merge_providers(builtin, override)
    kimi = next(p for p in result if p.id == "kimi")
    assert set(m.id for m in kimi.models) == {"k1", "k2", "k3"}
