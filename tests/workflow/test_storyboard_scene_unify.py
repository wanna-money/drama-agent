"""_unify_scene_fields: 同场景 lighting / color_temp / location 收敛到首镜取值。

location 一并收敛是本次新增行为——之前只收敛 lighting/color_temp,LLM 逐镜漂移出的
location 文案变体(如"外景 青云宗论道台 - 黄昏" vs "- 继续")会被 reference_service
按字面值去重,凭空多出一条不存在的背景参考图占位。这里直接测函数,不测到
reference_service 那一层(该层已有独立的 dedup key 假设,不是本次改动范围)。
"""
from drama_agent.workflow.nodes.storyboard_director import _unify_scene_fields


def _shot(scene=1, shot_no=1, lighting="natural", color_temp="neutral", location="INT", **overrides):
    base = {
        "scene_number": scene,
        "shot_number": shot_no,
        "lighting": lighting,
        "color_temp": color_temp,
        "location": location,
    }
    base.update(overrides)
    return base


def test_unify_scene_fields_converges_location_to_first_shot_of_scene():
    shots = [
        _shot(shot_no=1, location="外景 青云宗论道台 - 黄昏"),
        _shot(shot_no=2, location="外景 青云宗论道台 - 继续"),
        _shot(shot_no=3, location="外景 青云宗论道台"),
    ]
    out = _unify_scene_fields(shots)
    assert [s["location"] for s in out] == ["外景 青云宗论道台 - 黄昏"] * 3


def test_unify_scene_fields_converges_lighting_and_color_temp_to_first_shot():
    shots = [
        _shot(shot_no=1, lighting="natural", color_temp="warm"),
        _shot(shot_no=2, lighting="dramatic", color_temp="cool"),
    ]
    out = _unify_scene_fields(shots)
    assert [(s["lighting"], s["color_temp"]) for s in out] == [("natural", "warm")] * 2


def test_unify_scene_fields_does_not_mix_across_different_scenes():
    shots = [
        _shot(scene=1, shot_no=1, location="内景 咖啡馆 - 日"),
        _shot(scene=2, shot_no=1, location="外景 山道 - 夜"),
        _shot(scene=1, shot_no=2, location="内景 咖啡馆 - 继续"),
        _shot(scene=2, shot_no=2, location="外景 山道 - 继续"),
    ]
    out = _unify_scene_fields(shots)
    by_scene = {(s["scene_number"], s["shot_number"]): s["location"] for s in out}
    assert by_scene[(1, 1)] == "内景 咖啡馆 - 日"
    assert by_scene[(1, 2)] == "内景 咖啡馆 - 日"
    assert by_scene[(2, 1)] == "外景 山道 - 夜"
    assert by_scene[(2, 2)] == "外景 山道 - 夜"


def test_unify_scene_fields_leaves_already_consistent_shots_untouched():
    shots = [
        _shot(shot_no=1, location="内景 咖啡馆 - 日"),
        _shot(shot_no=2, location="内景 咖啡馆 - 日"),
    ]
    out = _unify_scene_fields(shots)
    assert out == shots
