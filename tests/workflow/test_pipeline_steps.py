from drama_agent.workflow.pipeline_steps import build_pipeline


def test_pipeline_excludes_keyframes_when_off():
    p = build_pipeline(use_keyframes=False, current_stage="story_analyzed")
    keys = [s["key"] for s in p["steps"]]
    assert "keyframes" not in keys
    assert keys == ["analysis", "screenplay", "screenplay_review", "storyboard",
                    "looks", "prompts", "video", "done"]


def test_pipeline_inserts_keyframes_before_video_when_on():
    p = build_pipeline(use_keyframes=True, current_stage=None)
    keys = [s["key"] for s in p["steps"]]
    assert keys.index("keyframes") == keys.index("video") - 1  # 恰在生成视频前


def test_current_maps_stage_to_step_key():
    # 造型/关键帧中断点归入对应步(修复前它们被并进分镜/生成视频)
    assert build_pipeline(False, "look_review")["current"] == "looks"
    assert build_pipeline(True, "keyframes_review")["current"] == "keyframes"
    assert build_pipeline(False, "prompts_review")["current"] == "prompts"
    assert build_pipeline(False, "completed")["current"] == "done"


def test_current_none_for_unmapped_stage():
    assert build_pipeline(False, "created")["current"] is None
    assert build_pipeline(False, None)["current"] is None
