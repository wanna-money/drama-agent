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


# ── 输出语言:共享规则必须覆盖所有 LLM 节点(#6/#7 的回归拦截) ──────────
def test_every_llm_node_system_prompt_carries_output_language_rule():
    """所有 LLM 节点的 SYSTEM 都必须带上共享的输出语言规则。

    这条规则原先靠各节点手抄一句中文,4 个节点只有 2 个抄到 —— 分镜与视频 prompt
    因此长期输出英文。收敛成共享常量后,这个测试保证新增/改动节点不会再漏掉。
    """
    from drama_agent.workflow.prompt_rules import OUTPUT_LANGUAGE_RULE
    from drama_agent.workflow.nodes import (
        story_analyzer, screenplay_writer, storyboard_director, prompt_engineer,
    )
    for mod in (story_analyzer, screenplay_writer, storyboard_director, prompt_engineer):
        assert OUTPUT_LANGUAGE_RULE in mod.SYSTEM, f"{mod.__name__} 缺少输出语言规则"


def test_screenplay_revision_node_carries_output_language_rule():
    """剧本"退回修改"节点也要带规则 —— 漏掉会把已通过的中文剧本改成英文再喂给分镜。"""
    import asyncio
    from unittest.mock import AsyncMock, patch
    from drama_agent.workflow.graph import screenplay_revision_node
    from drama_agent.workflow.prompt_rules import OUTPUT_LANGUAGE_RULE

    fake = AsyncMock(return_value="修改后的剧本")
    with patch("drama_agent.services.llm_service.llm_service.complete", fake):
        asyncio.run(screenplay_revision_node({
            "screenplay": "原剧本", "screenplay_revision_notes": "改开头", "llm_model": "m",
        }))
    system = fake.await_args.args[0]
    assert OUTPUT_LANGUAGE_RULE in system


def test_storyboard_few_shot_example_is_chinese_but_keeps_enum_tokens_english():
    """few-shot 示例得是中文(模型会照抄示例语言),但 shot_type/camera_movement 必须留英文枚举
    —— 它们要过 _coerce_enum,翻译了就会全部落到默认值。"""
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    from drama_agent.workflow.constants import ShotType, CameraMovement
    _, user = build_prompt("INT. X - DAY", {})
    assert "COFFEE SHOP" not in user            # 旧英文示例已替掉
    assert '"location": "内景 咖啡馆 - 日"' in user
    assert f'"shot_type": "{ShotType.ELS.value}"' in user
    assert f'"camera_movement": "{CameraMovement.STATIC.value}"' in user


def test_prompt_engineer_does_not_delegate_language_choice_to_model():
    """无模型专属指引时的兜底文案不能再把语言选择交还给模型(旧文案:
    "in the language that model expects"),否则和强制中文规则直接打架。"""
    from drama_agent.workflow.nodes.prompt_engineer import build_prompt
    shot = {
        "shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
        "location": "内景 房间", "description": "一张脸", "action": "微笑",
        "dialogue": "", "characters": [],
    }
    _, user = build_prompt(
        shot, char_descriptions=[], templates=[], cin_rules=[], provider="seedance",
        guides=None,
    )
    assert "language that model expects" not in user


# ── 目标时长驱动篇幅,且禁止 LLM 自编时长表头(#9) ───────────────────────
def test_screenplay_prompt_carries_target_duration_and_forbids_invented_header():
    """剧本 prompt 必须给出目标时长(否则 LLM 自由发挥),并明确禁止输出"时长：约N分钟"
    这类表头元信息 —— 那个数字既没依据、也和实际出片长度无关。"""
    from drama_agent.workflow.nodes.screenplay_writer import build_prompt
    _, user = build_prompt({"title": "T", "characters": []}, target_seconds=90)
    assert "90 秒" in user
    assert "1 分 30 秒" in user
    assert "不要" in user and "元信息表头" in user


def test_storyboard_prompt_constrains_total_shot_duration_to_target():
    """分镜 prompt 要把镜头总时长约束到目标时长,否则会出 37 个镜头这种失控篇幅。"""
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    _, user = build_prompt("INT. X - DAY", {}, target_seconds=100)
    assert "100 秒" in user
    assert "duration_seconds" in user


def test_both_nodes_default_target_duration_to_config():
    """不显式传时,两个节点都该落到 config 的 target_episode_seconds(单一默认来源)。"""
    from drama_agent.config import settings
    from drama_agent.workflow.nodes.screenplay_writer import build_prompt as sp
    from drama_agent.workflow.nodes.storyboard_director import build_prompt as sb
    marker = f"{settings.target_episode_seconds} 秒"
    assert marker in sp({"title": "T", "characters": []})[1]
    assert marker in sb("INT. X - DAY", {})[1]
