def test_story_analyzer_build_prompt_contains_inputs():
    from drama_agent.workflow.nodes.story_analyzer import build_prompt, SYSTEM
    system, user = build_prompt("A lonely astronaut finds a plant.", genre="drama")
    assert system == SYSTEM
    assert "A lonely astronaut finds a plant." in user
    assert "drama" in user
    assert "characters" in user and "appearance" in user


def test_story_analyzer_build_prompt_lists_genre_enum_values():
    """prompt 里的合法类型清单须来自 Genre 枚举(单一源,不手写)——防前后端取值漂移。"""
    from drama_agent.workflow.nodes.story_analyzer import build_prompt
    from drama_agent.db.enums import Genre
    _, user = build_prompt("X")
    for g in Genre:
        assert g.value in user


def test_screenplay_writer_build_prompt_uses_analysis():
    from drama_agent.workflow.nodes.screenplay_writer import build_prompt, SYSTEM
    analysis = {
        "title": "Red Balloon", "genre": "drama", "setting": "Paris 1950s",
        "tone": "wistful", "themes": ["freedom", "childhood"],
        "plot_summary": "A boy befriends a balloon.", "scene_count_estimate": 4,
        "characters": [{"name": "Pascal", "appearance": "small boy, red coat", "personality": "curious"}],
    }
    system, user = build_prompt(analysis)
    assert system == SYSTEM
    assert "Red Balloon" in user and "Paris 1950s" in user
    assert "Pascal" in user and "red coat" in user
    assert "freedom" in user


def test_storyboard_build_prompt_embeds_screenplay_and_chars():
    from drama_agent.workflow.nodes.storyboard_director import build_prompt, SYSTEM
    analysis = {"characters": [{"name": "Mia", "appearance": "tall, blonde"}]}
    system, user = build_prompt("INT. CAFE - DAY\nMia enters.", analysis)
    assert system == SYSTEM
    assert "INT. CAFE - DAY" in user
    assert "Mia" in user and "tall, blonde" in user
    assert "duration_seconds" in user


def test_storyboard_build_prompt_lists_enum_values():
    """build_prompt 里列出的合法镜头类型/运镜须来自枚举(单一源,不手写)。"""
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    from drama_agent.workflow.constants import ShotType, CameraMovement, MAX_SHOT_DURATION
    _, user = build_prompt("INT. X - DAY", {})
    for t in ShotType:
        assert t.value in user
    for c in CameraMovement:
        assert c.value in user
    assert str(MAX_SHOT_DURATION) in user


def test_prompt_engineer_build_prompt_pure_with_injected_rag():
    from drama_agent.workflow.nodes.prompt_engineer import build_prompt, SYSTEM
    shot = {
        "shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
        "location": "INT. ROOM", "description": "a face", "action": "smiles",
        "dialogue": "", "characters": ["Ana"],
    }
    system, user = build_prompt(
        shot, char_descriptions=["Ana: red hair"],
        templates=["tmpl-A"], cin_rules=["rule-A"], provider="seedance",
    )
    assert system == SYSTEM
    assert "CU" in user and "a face" in user
    assert "Ana: red hair" in user
    assert "tmpl-A" in user and "rule-A" in user
    assert "seedance" in user
    assert "prompt_text" in user and "negative_prompt" in user


def test_prompt_engineer_build_prompt_includes_notes_when_provided():
    """退回重新生成时,人工意见必须真正拼进 user prompt,否则「退回」对用户是假的。"""
    from drama_agent.workflow.nodes.prompt_engineer import build_prompt
    shot = {
        "shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
        "location": "INT. ROOM", "description": "a face", "action": "smiles",
        "dialogue": "", "characters": ["Ana"],
    }
    _, user = build_prompt(
        shot, char_descriptions=["Ana: red hair"],
        templates=["tmpl-A"], cin_rules=["rule-A"], provider="seedance",
        notes="镜头太暗，改成白天室外场景",
    )
    assert "镜头太暗，改成白天室外场景" in user
    # 锁定段落标题本身,防止未来改标题文案时这条测试仍绿、而 omit 测试却悄悄失去覆盖力
    assert "Revision notes" in user


def test_prompt_engineer_build_prompt_omits_notes_section_when_absent():
    """没有 notes(首次生成,非退回)或 notes 为纯空白时,不应输出空白/占位的意见段落。"""
    from drama_agent.workflow.nodes.prompt_engineer import build_prompt
    shot = {
        "shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
        "location": "INT. ROOM", "description": "a face", "action": "smiles",
        "dialogue": "", "characters": ["Ana"],
    }
    _, user_with_none = build_prompt(
        shot, char_descriptions=["Ana: red hair"],
        templates=["tmpl-A"], cin_rules=["rule-A"], provider="seedance",
    )
    _, user_with_empty = build_prompt(
        shot, char_descriptions=["Ana: red hair"],
        templates=["tmpl-A"], cin_rules=["rule-A"], provider="seedance", notes="",
    )
    _, user_with_whitespace = build_prompt(
        shot, char_descriptions=["Ana: red hair"],
        templates=["tmpl-A"], cin_rules=["rule-A"], provider="seedance", notes="   \n\t",
    )
    assert "Revision notes" not in user_with_none
    assert "Revision notes" not in user_with_empty
    assert "Revision notes" not in user_with_whitespace


def test_screenplay_build_prompt_includes_knowledge_guide():
    from drama_agent.workflow.nodes.screenplay_writer import build_prompt
    from drama_agent.knowledge.constants import SCREENPLAY_GUIDE
    _, user = build_prompt({"title": "T", "characters": []})
    assert any(g in user for g in SCREENPLAY_GUIDE)


def test_storyboard_build_prompt_includes_knowledge_guide():
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    from drama_agent.knowledge.constants import STORYBOARD_GUIDE
    from drama_agent.workflow.constants import ShotType
    _, user = build_prompt("INT. X - DAY", {})
    assert any(g in user for g in STORYBOARD_GUIDE)
    # 硬约束枚举仍在(承接上一轮)
    for t in ShotType:
        assert t.value in user

