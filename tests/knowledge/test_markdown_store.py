def test_craft_kinds_read_full_doc():
    from drama_agent.knowledge.store import MarkdownKnowledgeStore
    store = MarkdownKnowledgeStore()
    for kind, marker in [
        ("shot_language", "景别"),
        ("story_structure", "节拍"),
        ("visual_aesthetics", "视觉强度"),
    ]:
        out = store.retrieve(kind)
        assert isinstance(out, list) and len(out) == 1
        assert marker in out[0]


def test_non_craft_kind_returns_empty():
    # 瘦身后 markdown 只服务 CRAFT_KINDS;非 craft 返回 [],路由/兜底交给 registry。
    from drama_agent.knowledge.store import MarkdownKnowledgeStore
    store = MarkdownKnowledgeStore()
    assert store.retrieve("prompt_template", key="CU", k=2) == []


def test_missing_craft_file_returns_empty(monkeypatch):
    from drama_agent.knowledge import store as store_mod
    monkeypatch.setattr(store_mod, "_read_craft", lambda kind: "")
    s = store_mod.MarkdownKnowledgeStore()
    assert s.retrieve("shot_language") == []


def test_default_store_is_registry_without_dify(monkeypatch):
    from drama_agent.knowledge import store as store_mod
    from drama_agent.knowledge.registry import KnowledgeRegistry
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "dify_base_url", "", raising=False)
    monkeypatch.setattr(settings, "knowledge_backends", [], raising=False)
    r = store_mod._default_store()
    assert isinstance(r, KnowledgeRegistry)
    out = r.retrieve("shot_language")
    assert isinstance(out, list) and len(out) == 1 and "景别" in out[0]


def test_default_store_is_registry_with_dify(monkeypatch):
    from drama_agent.knowledge import store as store_mod
    from drama_agent.knowledge.registry import KnowledgeRegistry
    from drama_agent.config import settings
    monkeypatch.setattr(settings, "dify_base_url", "http://dify.local", raising=False)
    monkeypatch.setattr(settings, "dify_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "dify_dataset_ids", {"screenplay_guide": "ds1"}, raising=False)
    monkeypatch.setattr(settings, "knowledge_backends", [], raising=False)
    assert isinstance(store_mod._default_store(), KnowledgeRegistry)


def test_craft_files_are_packaged():
    from drama_agent.knowledge.store import _read_craft, CRAFT_KINDS
    for kind in CRAFT_KINDS:
        assert _read_craft(kind).strip() != ""
