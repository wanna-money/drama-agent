"""仙侠/打斗类 craft 知识只在题材命中时才检索,避免非战斗题材被无关内容稀释。"""
from drama_agent.workflow.nodes import prompt_engineer, storyboard_director


def test_storyboard_prompt_includes_combat_knowledge_for_fantasy_genre():
    _, user_prompt = storyboard_director.build_prompt(
        "INT. ROOM\nA fights B.", {}, target_seconds=60, genre="fantasy")
    assert "Combat/VFX reference" in user_prompt


def test_storyboard_prompt_omits_combat_knowledge_for_non_combat_genre():
    _, user_prompt = storyboard_director.build_prompt(
        "INT. ROOM\nThey talk.", {}, target_seconds=60, genre="romance")
    assert "Combat/VFX reference" not in user_prompt


def test_storyboard_prompt_omits_combat_knowledge_when_genre_omitted():
    """默认(未传 genre)不应意外拉入战斗知识——向后兼容旧调用点。"""
    _, user_prompt = storyboard_director.build_prompt(
        "INT. ROOM\nThey talk.", {}, target_seconds=60)
    assert "Combat/VFX reference" not in user_prompt


def _shot(**overrides):
    base = {
        "shot_id": "s1", "shot_type": "MS", "camera_movement": "static",
        "lighting": "natural", "color_temp": "neutral", "duration_seconds": 3,
        "location": "INT", "description": "d", "action": "he moves",
        "dialogue": "", "characters": [],
    }
    base.update(overrides)
    return base


def test_prompt_engineer_includes_lighting_knowledge_when_passed():
    _, user_prompt = prompt_engineer.build_prompt(
        _shot(), [], [], [], "seedance", lighting_knowledge=["丁达尔光", "轮廓光"])
    assert "丁达尔光" in user_prompt


def test_prompt_engineer_omits_lighting_knowledge_line_when_not_passed():
    _, user_prompt = prompt_engineer.build_prompt(
        _shot(), [], [], [], "seedance")
    assert "该题材的光影关键词参考" not in user_prompt
