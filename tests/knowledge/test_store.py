def test_retrieve_prompt_template_by_shot_type():
    """key 要真的路由到对应景别的桶(而不是别的景别/兜底)。断言比对常量源本身,
    这样改文案不会误报,但取错桶必然被抓到。"""
    from drama_agent.knowledge.constants import PROMPT_TEMPLATES
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("prompt_template", key="CU", k=2)
    assert out and out[0] in PROMPT_TEMPLATES["seedance"]["CU"]
    assert out[0] not in PROMPT_TEMPLATES["seedance"]["LS"]
    assert len(out) <= 2


def test_retrieve_cinematography_by_category():
    from drama_agent.knowledge.constants import CINEMATOGRAPHY
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("cinematography", key="camera")
    assert out and out[0] in CINEMATOGRAPHY["camera"]
    assert out[0] not in CINEMATOGRAPHY["lighting"]


def test_retrieve_screenplay_guide():
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("screenplay_guide")
    assert out and len(out) >= 1


def test_retrieve_unknown_kind_returns_empty():
    from drama_agent.knowledge.store import knowledge_store
    assert knowledge_store.retrieve("nonsense") == []


def test_retrieve_k_limits():
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("screenplay_guide", k=1)
    assert len(out) <= 1


def test_pgvector_store_not_implemented():
    import pytest
    from drama_agent.knowledge.pgvector_store import PgVectorKnowledgeStore
    with pytest.raises(NotImplementedError):
        PgVectorKnowledgeStore().retrieve("prompt_template")
