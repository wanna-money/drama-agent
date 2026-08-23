from unittest.mock import patch


def _fake_retrieve(mapping):
    def _r(kind, key=None, query=None, k=3):
        return mapping.get(kind, [])
    return _r


def test_screenplay_prompt_includes_story_structure():
    from drama_agent.workflow.nodes import screenplay_writer as sw
    mapping = {"screenplay_guide": ["G1"], "story_structure": ["STORY_STRUCTURE_SENTINEL"]}
    with patch.object(sw.knowledge_store, "retrieve", _fake_retrieve(mapping)):
        _system, user = sw.build_prompt({"title": "T", "characters": []})
    assert "STORY_STRUCTURE_SENTINEL" in user
    assert "G1" in user


def test_storyboard_prompt_includes_shot_language_and_visual():
    from drama_agent.workflow.nodes import storyboard_director as sd
    mapping = {
        "storyboard_guide": ["SBG"],
        "shot_language": ["SHOT_LANG_SENTINEL"],
        "visual_aesthetics": ["VISUAL_SENTINEL"],
    }
    with patch.object(sd.knowledge_store, "retrieve", _fake_retrieve(mapping)):
        _system, user = sd.build_prompt("SCREENPLAY", {"characters": []})
    assert "SHOT_LANG_SENTINEL" in user
    assert "VISUAL_SENTINEL" in user
    assert "SBG" in user


def test_prompts_omit_methodology_when_empty():
    from drama_agent.workflow.nodes import screenplay_writer as sw
    with patch.object(sw.knowledge_store, "retrieve", _fake_retrieve({"screenplay_guide": ["G1"]})):
        _system, user = sw.build_prompt({"title": "T", "characters": []})
    assert "STORY_STRUCTURE_SENTINEL" not in user
    assert isinstance(user, str) and len(user) > 0
