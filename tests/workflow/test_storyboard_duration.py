"""storyboard_director 的时长逻辑:duration_seconds 是纯叙事时长,不再被钳到
任何模型相关下限;_rhythm_ok 只检查时长多样性;_converge_duration 削峰不设地板。
"""
from unittest.mock import AsyncMock

import pytest

from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.constants import MAX_SHOT_DURATION
from drama_agent.workflow.nodes.storyboard_director import (
    _converge_duration,
    _generate_shots,
    _rhythm_ok,
)


def _shot(scene=1, shot_no=1, duration=5, **overrides):
    base = {
        "scene_number": scene,
        "shot_number": shot_no,
        "shot_type": "MS",
        "camera_movement": "static",
        "lighting": "natural",
        "color_temp": "neutral",
        "duration_seconds": duration,
        "beats": None,
        "location": "INT",
        "description": "d",
        "characters": [],
        "action": "he moves",
        "dialogue": "",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_generate_shots_does_not_clamp_narrative_duration_to_a_floor(monkeypatch):
    """LLM 给的 1 秒短镜头(如一次击中)必须原样保留,不再被拉到任何"5s 类"下限。"""
    monkeypatch.setattr(
        llm_service, "complete_json",
        AsyncMock(return_value=[_shot(duration=1)]),
    )
    state = {"screenplay": "INT. ROOM\nHe is hit.", "story_analysis": {}, "llm_model": None}

    shots = await _generate_shots(state, target_seconds=60, cast_names=[], notes=None)

    assert shots[0]["duration_seconds"] == 1
    assert "narrative_duration_seconds" not in shots[0]


@pytest.mark.asyncio
async def test_generate_shots_clamps_only_to_narrative_ceiling(monkeypatch):
    """超过叙事上限(MAX_SHOT_DURATION)时仍要夹,这条边界没有变。"""
    monkeypatch.setattr(
        llm_service, "complete_json",
        AsyncMock(return_value=[_shot(duration=MAX_SHOT_DURATION + 50)]),
    )
    state = {"screenplay": "INT. ROOM\nLong beat.", "story_analysis": {}, "llm_model": None}

    shots = await _generate_shots(state, target_seconds=60, cast_names=[], notes=None)

    assert shots[0]["duration_seconds"] == MAX_SHOT_DURATION


def test_rhythm_ok_rejects_uniform_durations():
    shots = [_shot(duration=5), _shot(duration=5), _shot(duration=5)]
    reason = _rhythm_ok(shots, target_seconds=60)
    assert reason
    assert "1 种取值" in reason


def test_rhythm_ok_accepts_three_distinct_durations():
    shots = [_shot(duration=1), _shot(duration=5), _shot(duration=8)]
    assert _rhythm_ok(shots, target_seconds=60) == ""


def test_rhythm_ok_no_longer_checks_shot_count_times_floor():
    """旧逻辑会在"镜头数 × 下限超目标"时拒绝;新模型没有统一下限,这条检查已删除
    —— 大量短镜头(时长各异)即使数量很多也不该被这条规则拦下。"""
    shots = [_shot(shot_no=i, duration=(i % 5) + 1) for i in range(40)]
    assert _rhythm_ok(shots, target_seconds=10) == ""


def test_converge_duration_shaves_without_a_floor():
    """总时长超标时削峰,可以一直削到 1 秒 —— 不再有 5s 地板。

    旧逻辑遇到"镜头数 × 5s 下限已经超标"(5 镜 × 5s = 25s > 目标 5s)时,会在
    所有镜头都触及下限后停手,总时长仍然是 25s、超标(duration_over_target=True)。
    新逻辑没有下限,能一路削到 1 秒,总和精确落在目标内。
    """
    shots = [_shot(shot_no=i, duration=8) for i in range(5)]  # total = 40

    converged, over = _converge_duration(shots, target_seconds=5)

    total = sum(s["duration_seconds"] for s in converged)
    assert total == 5
    assert not over
    assert all(s["duration_seconds"] == 1 for s in converged)


def test_converge_duration_leaves_totals_within_target_untouched():
    shots = [_shot(duration=3), _shot(duration=4)]
    converged, over = _converge_duration(shots, target_seconds=60)
    assert converged == shots
    assert not over
