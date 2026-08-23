def test_score_story_analysis_pass_and_fail():
    from drama_agent.evals.scorers import score_story_analysis
    good = {"title": "T", "setting": "s", "themes": ["a"],
            "characters": [{"name": "X", "appearance": "tall"}]}
    scores = score_story_analysis("{...}", good)
    assert all(s["passed"] for s in scores)

    bad = {"title": "T"}  # 缺 characters/setting/themes
    scores_bad = score_story_analysis("{}", bad)
    assert any(not s["passed"] for s in scores_bad)


def test_score_storyboard_duration_rule():
    from drama_agent.evals.scorers import score_storyboard
    ok = [{"duration_seconds": 5, "shot_type": "CU"}]
    assert all(s["passed"] for s in score_storyboard("[]", ok))
    bad = [{"duration_seconds": 20, "shot_type": "CU"}]  # >10
    assert any(not s["passed"] for s in score_storyboard("[]", bad))


def test_score_prompt_requires_fields():
    from drama_agent.evals.scorers import score_prompt
    assert all(s["passed"] for s in score_prompt("{}", {"prompt_text": "x", "negative_prompt": "y"}))
    assert any(not s["passed"] for s in score_prompt("{}", {"prompt_text": ""}))


def test_score_screenplay_scene_markers():
    from drama_agent.evals.scorers import score_screenplay
    assert all(s["passed"] for s in score_screenplay("INT. CAFE - DAY\naction"))
    assert any(not s["passed"] for s in score_screenplay("no markers here"))
