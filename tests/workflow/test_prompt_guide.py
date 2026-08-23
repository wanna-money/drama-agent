from unittest.mock import patch, MagicMock


def test_prompt_template_composite_key_single_provider():
    from drama_agent.knowledge.store import ConstantKnowledgeStore
    s = ConstantKnowledgeStore()
    seed = s.retrieve("prompt_template", key="seedance:CU")
    assert seed and all("Seedance" in t or "seedance" in t.lower() for t in seed)
    assert not any("近景特写" in t for t in seed)  # 其它 provider 的中文模板不得混入
    assert isinstance(s.retrieve("prompt_template", key="CU"), list)  # backward compat


def test_prompt_template_composite_unknown_provider_empty():
    from drama_agent.knowledge.store import ConstantKnowledgeStore
    assert ConstantKnowledgeStore().retrieve("prompt_template", key="minimax:CU") == []


def test_build_prompt_injects_model_guide():
    from drama_agent.workflow.nodes import prompt_engineer as pe
    shot = {"shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
            "location": "L", "description": "D", "action": "A", "dialogue": "", "characters": []}
    system, user = pe.build_prompt(shot, [], ["TMPL"], ["CIN"], "seedance", ["GUIDE_SENTINEL"])
    assert "GUIDE_SENTINEL" in user


def test_build_prompt_guide_fallback_when_empty():
    from drama_agent.workflow.nodes import prompt_engineer as pe
    shot = {"shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
            "location": "L", "description": "D", "action": "A", "dialogue": "", "characters": []}
    system, user = pe.build_prompt(shot, [], ["TMPL"], ["CIN"], "custommodel", [])
    assert isinstance(user, str) and len(user) > 0
    assert "GUIDE_SENTINEL" not in user


def test_guide_key_for_resolves_and_degrades():
    from drama_agent.workflow.nodes import prompt_engineer as pe
    import drama_agent.provider as provider_pkg
    m = MagicMock()
    m.prompt_guide_key = "seedance"
    reg = MagicMock()
    reg.resolve_model.return_value = (MagicMock(), m)
    with patch.object(provider_pkg, "provider_registry", reg):
        assert pe._guide_key_for("seedance") == "seedance"
    reg2 = MagicMock()
    reg2.resolve_model.side_effect = ValueError("unknown")
    with patch.object(provider_pkg, "provider_registry", reg2):
        assert pe._guide_key_for("nope") is None
