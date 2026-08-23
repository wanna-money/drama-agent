def test_retrieve_prompt_template_by_shot_type():
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("prompt_template", key="CU", k=2)
    assert out and any("Close-up" in x or "近景" in x for x in out)
    assert len(out) <= 2


def test_retrieve_cinematography_by_category():
    from drama_agent.knowledge.store import knowledge_store
    out = knowledge_store.retrieve("cinematography", key="camera")
    assert out and "Camera movements" in out[0]


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
