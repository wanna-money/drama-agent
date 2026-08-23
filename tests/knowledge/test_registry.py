import pytest
from unittest.mock import MagicMock


def _decl(**kw):
    from drama_agent.knowledge.registry import KnowledgeBackendDecl
    return KnowledgeBackendDecl(**kw)


def _mock_store(ret):
    s = MagicMock()
    s.retrieve = MagicMock(return_value=ret)
    return s


def test_unknown_type_raises():
    from drama_agent.knowledge.registry import KnowledgeRegistry
    with pytest.raises(ValueError, match="Unknown knowledge backend type"):
        KnowledgeRegistry([_decl(id="x", type="nope", kinds=["a"])])


def test_duplicate_kind_ownership_raises():
    from drama_agent.knowledge.registry import KnowledgeRegistry
    with pytest.raises(ValueError, match="more than one backend"):
        KnowledgeRegistry([
            _decl(id="a", type="constant", kinds=["prompt_guide"]),
            _decl(id="b", type="markdown", kinds=["prompt_guide"]),
        ])


def test_multiple_fallback_raises():
    from drama_agent.knowledge.registry import KnowledgeRegistry
    with pytest.raises(ValueError, match="multiple fallback"):
        KnowledgeRegistry([
            _decl(id="a", type="constant", fallback=True),
            _decl(id="b", type="markdown", fallback=True),
        ])


def test_primary_hit_returns_primary(monkeypatch):
    import drama_agent.knowledge.registry as reg
    monkeypatch.setitem(reg.BACKEND_TYPES, "P", lambda cfg: _mock_store(["PRIMARY"]))
    monkeypatch.setitem(reg.BACKEND_TYPES, "F", lambda cfg: _mock_store(["FALLBACK"]))
    r = reg.KnowledgeRegistry([
        _decl(id="p", type="P", kinds=["k1"]),
        _decl(id="f", type="F", fallback=True),
    ])
    assert r.retrieve("k1") == ["PRIMARY"]


def test_unclaimed_kind_goes_fallback(monkeypatch):
    import drama_agent.knowledge.registry as reg
    monkeypatch.setitem(reg.BACKEND_TYPES, "P", lambda cfg: _mock_store(["PRIMARY"]))
    monkeypatch.setitem(reg.BACKEND_TYPES, "F", lambda cfg: _mock_store(["FALLBACK"]))
    r = reg.KnowledgeRegistry([
        _decl(id="p", type="P", kinds=["k1"]),
        _decl(id="f", type="F", fallback=True),
    ])
    assert r.retrieve("k_other") == ["FALLBACK"]


def test_primary_empty_falls_back(monkeypatch):
    import drama_agent.knowledge.registry as reg
    monkeypatch.setitem(reg.BACKEND_TYPES, "P", lambda cfg: _mock_store([]))
    monkeypatch.setitem(reg.BACKEND_TYPES, "F", lambda cfg: _mock_store(["FALLBACK"]))
    r = reg.KnowledgeRegistry([
        _decl(id="p", type="P", kinds=["k1"]),
        _decl(id="f", type="F", fallback=True),
    ])
    assert r.retrieve("k1") == ["FALLBACK"]


def test_primary_raises_falls_back(monkeypatch):
    import drama_agent.knowledge.registry as reg
    boom = MagicMock()
    boom.retrieve = MagicMock(side_effect=RuntimeError("down"))
    monkeypatch.setitem(reg.BACKEND_TYPES, "P", lambda cfg: boom)
    monkeypatch.setitem(reg.BACKEND_TYPES, "F", lambda cfg: _mock_store(["FALLBACK"]))
    r = reg.KnowledgeRegistry([
        _decl(id="p", type="P", kinds=["k1"]),
        _decl(id="f", type="F", fallback=True),
    ])
    assert r.retrieve("k1") == ["FALLBACK"]


def test_no_fallback_returns_empty(monkeypatch):
    import drama_agent.knowledge.registry as reg
    monkeypatch.setitem(reg.BACKEND_TYPES, "P", lambda cfg: _mock_store([]))
    r = reg.KnowledgeRegistry([_decl(id="p", type="P", kinds=["k1"])])
    assert r.retrieve("k1") == []
    assert r.retrieve("unknown") == []


def test_default_registry_without_dify_routes_craft_to_markdown(monkeypatch):
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "dify_base_url", "", raising=False)
    monkeypatch.setattr(settings, "knowledge_backends", [], raising=False)
    from drama_agent.knowledge.registry import build_default_registry
    r = build_default_registry()
    out = r.retrieve("shot_language")
    assert isinstance(out, list) and len(out) == 1 and "景别" in out[0]


def test_default_registry_with_dify_still_routes_craft_local(monkeypatch):
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.local", raising=False)
    monkeypatch.setattr(settings, "dify_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "dify_dataset_ids", {"screenplay_guide": "ds1"}, raising=False)
    monkeypatch.setattr(settings, "knowledge_backends", [], raising=False)
    from drama_agent.knowledge.registry import build_default_registry
    r = build_default_registry()
    out = r.retrieve("story_structure")
    assert isinstance(out, list) and len(out) == 1 and "节拍" in out[0]


def test_registry_dify_fail_falls_back_to_constant(monkeypatch):
    """瘦身后 dify 抛/空,兜底责任在 registry:整链仍降级到 constant(非空)。"""
    import httpx
    from drama_agent.knowledge.registry import KnowledgeRegistry, KnowledgeBackendDecl
    r = KnowledgeRegistry([
        KnowledgeBackendDecl(
            id="biz", type="dify", kinds=["prompt_template"],
            config={"base_url": "http://dify.local", "api_key": "k",
                    "dataset_ids": {"prompt_template": "ds1"}, "timeout": 5},
        ),
        KnowledgeBackendDecl(id="base", type="constant", fallback=True),
    ])
    biz = r._by_kind["prompt_template"]
    monkeypatch.setattr(biz, "_post", MagicMock(side_effect=httpx.ConnectError("down")))
    out = r.retrieve("prompt_template", key="CU", k=2)
    assert out and any("Close-up" in x or "近景" in x for x in out)
