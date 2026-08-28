from drama_agent.workflow.pipeline_steps import build_pipeline


def test_pipeline_excludes_keyframes_when_off():
    p = build_pipeline("from_story", use_keyframes=False, current_stage="story_analyzed")
    keys = [s["key"] for s in p["steps"]]
    assert "keyframes" not in keys


def test_pipeline_inserts_keyframes_before_video_when_on():
    p = build_pipeline("from_story", use_keyframes=True, current_stage=None)
    keys = [s["key"] for s in p["steps"]]
    assert keys.index("keyframes") == keys.index("video") - 1


def test_current_maps_stage_to_step_key():
    assert build_pipeline("from_story", False, "look_review")["current"] == "looks"
    assert build_pipeline("from_story", True, "keyframes_review")["current"] == "keyframes"
    assert build_pipeline("from_story", False, "prompts_review")["current"] == "prompts"
    assert build_pipeline("from_story", False, "completed")["current"] == "done"


def test_current_none_for_unmapped_stage():
    assert build_pipeline("from_story", False, "created")["current"] is None
    assert build_pipeline("from_story", False, None)["current"] is None


# ── mode 参数:复用剧本时不展示剧本三步(它们视频侧根本不跑) ──────────────
def test_from_script_omits_screenplay_steps():
    p = build_pipeline("from_script", use_keyframes=False, current_stage="storyboard_start")
    keys = [s["key"] for s in p["steps"]]
    assert "analysis" not in keys
    assert "screenplay" not in keys
    assert "screenplay_review" not in keys
    assert keys[0] == "storyboard"
    assert p["current"] == "storyboard"


def test_from_story_includes_screenplay_steps():
    p = build_pipeline("from_story", use_keyframes=False, current_stage="starting")
    keys = [s["key"] for s in p["steps"]]
    assert keys[:4] == ["analysis", "cast", "screenplay", "screenplay_review"]
    assert p["current"] == "analysis"


def test_from_script_excludes_cast_step():
    """复用剧本/改编切片时图直达分镜,不经过 cast_review —— 展示出来就是永不执行的死步骤
    (I-2 修过同一类病:多出三个走不到的剧本步)。"""
    p = build_pipeline("from_script", use_keyframes=False, current_stage="storyboard_start")
    assert "cast" not in [s["key"] for s in p["steps"]]


def test_cast_stages_map_to_cast_step():
    """确认角色这一步的三个 stage 都要归到 cast:漏一个,那个阶段的事件会让当前步变 None
    (storyboard_start 是同类:曾漏映射导致首个事件 current=None)。"""
    for stage in ("cast_resolved", "cast_review", "cast_confirmed"):
        p = build_pipeline("from_story", use_keyframes=False, current_stage=stage)
        assert p["current"] == "cast", stage


def test_storyboard_start_belongs_to_storyboard_step():
    """storyboard_start 必须归到 storyboard 步:不属任何步会让首个事件 current=None。"""
    p = build_pipeline("from_script", use_keyframes=False, current_stage="storyboard_start")
    assert p["current"] == "storyboard"
