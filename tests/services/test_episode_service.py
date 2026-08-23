"""episode_service: aggregate_project_status 纯函数各状态组合(删了它状态聚合回归无人拦)。"""
from drama_agent.services.episode_service import aggregate_project_status


def test_empty_no_episodes():
    assert aggregate_project_status([]) == "empty"


def test_running_wins_over_others():
    assert aggregate_project_status(["completed", "running", "failed"]) == "running"
    assert aggregate_project_status(["queued", "completed"]) == "running"


def test_paused_when_no_running():
    assert aggregate_project_status(["completed", "paused", "failed"]) == "paused"


def test_all_completed():
    assert aggregate_project_status(["completed", "completed"]) == "completed"


def test_partial_failed_when_some_failed_not_all_completed():
    assert aggregate_project_status(["completed", "failed"]) == "partial_failed"


def test_created_only_is_running_bucket():
    # 有集但都还没跑完/未失败(created)→ 视为进行中(非 empty/completed)
    assert aggregate_project_status(["created"]) == "running"
