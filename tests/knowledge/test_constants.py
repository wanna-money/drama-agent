def test_prompt_templates_cover_providers_and_shot_types():
    from drama_agent.knowledge.constants import PROMPT_TEMPLATES
    assert "seedance" in PROMPT_TEMPLATES
    assert "CU" in PROMPT_TEMPLATES["seedance"]
    assert all(isinstance(v, list) for st in PROMPT_TEMPLATES.values() for v in st.values())


def test_cinematography_categories():
    from drama_agent.knowledge.constants import CINEMATOGRAPHY
    for cat in ("shot_type", "camera", "lighting", "continuity", "pacing"):
        assert cat in CINEMATOGRAPHY and CINEMATOGRAPHY[cat]


def test_guides_non_empty():
    from drama_agent.knowledge.constants import SCREENPLAY_GUIDE, STORYBOARD_GUIDE, PROMPT_GUIDES
    assert SCREENPLAY_GUIDE and STORYBOARD_GUIDE
    assert "seedance" in PROMPT_GUIDES
