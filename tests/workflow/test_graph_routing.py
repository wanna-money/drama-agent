"""统一图的条件入口:已有通过的剧本直达分镜,没有则从故事分析开始。

拦的路由接错会让"复用剧本"/"改编切片"/"从故事开始"走错边 —— 这是本设计的地基。
"""
import pytest
from unittest.mock import patch

from drama_agent.workflow import graph as g


@pytest.fixture(autouse=True)
def fresh_workspace(tmp_path, monkeypatch):
    """隔离图单例。这些用例都传 checkpointer=None,不开 aiosqlite 连接,
    因此不能在收尾里 close_graphs() —— 那会去关别的用例在别的事件循环上建的连接。
    """
    monkeypatch.setattr(g.settings, "langgraph_db_path", str(tmp_path / "cp.db"))
    saved = g._graph
    g._graph = None
    yield
    g._graph = saved


def _base_state(**overrides):
    s = {
        "project_id": "p1", "episode_id": "e1", "episode_number": 1, "title": "T",
        "raw_input": "", "genre": "drama", "story_analysis": None, "screenplay": "",
        "screenplay_approved": False, "screenplay_revision_notes": "",
        "shots": [], "prompts": [], "prompts_approved": False, "prompt_revision_notes": "",
        "use_keyframes": False, "keyframe_image_model": "", "keyframes_approved": False,
        "videos": [], "references": [], "look_assignments": {},
        "look_assignments_approved": False, "current_stage": "", "error": None,
        "llm_model": "m", "video_model": "", "video_provider": "seedance",
        "resolution": "768P", "assembled_video_path": None, "script_id": None,
    }
    s.update(overrides)
    return s


def test_route_entry_by_screenplay_approved():
    """入口按'是否已有通过的剧本'分流,而非死盯 script_id ——
    复用剧本、改编切片都置 approved=True → 直达分镜;从故事 approved=False → 故事分析。"""
    assert g.route_entry(_base_state(screenplay_approved=True)) == "storyboard_director"
    assert g.route_entry(_base_state(screenplay_approved=False)) == "story_analyzer"


@pytest.mark.asyncio
async def test_unified_graph_runs_from_story_when_no_script():
    """从故事开始:第一个节点必须是 story_analyzer(不是 storyboard)。"""
    graph = g.build_unified_graph(None)
    c = graph.get_graph()
    node_names = set(c.nodes)
    # 图里两个分支的节点都存在
    assert "story_analyzer" in node_names
    assert "storyboard_director" in node_names
    # START 的边必须能路由到两个入口(条件边 + 两个目标)
    starter = [e for e in c.edges if e.source == "__start__"]
    assert starter, "START 上没有边 —— 条件入口没接上"
    assert {e.target for e in starter} == {"story_analyzer", "storyboard_director"}


@pytest.mark.asyncio
async def test_unified_graph_review_node_still_interrupts_on_screenplay():
    """剧本审核节点仍是中断点(这是剧本 UI 搬进剧集页的前提)。"""
    with patch("drama_agent.workflow.graph.interrupt", return_value={"approved": True}):
        out = await g.screenplay_review_node(_base_state(screenplay="正文"))
    assert out["screenplay_approved"] is True


# ── 剧本审核后的去向(统一图接线)──────────────────────────────────────────────

def test_route_after_screenplay_review_approved_goes_to_storyboard():
    """通过 → 进制作段,与"复用剧本"/"改编切片"两条入口会聚到同一个 storyboard_director。

    合并成统一图前这里返回 END(剧本图到此为止),残留它会让"从故事开始"的集
    在剧本通过后原地终止,永远到不了分镜/视频。
    """
    assert g.route_after_screenplay_review(
        _base_state(screenplay_approved=True)) == "storyboard_director"


def test_route_after_screenplay_review_rejected_goes_to_revision():
    assert g.route_after_screenplay_review(
        _base_state(screenplay_approved=False)) == "screenplay_revision"


# ── 分镜审核回环(Task 6)──────────────────────────────────────────────────────

def test_route_after_storyboard_review_approved_goes_to_look():
    assert g.route_after_storyboard_review(
        _base_state(storyboard_approved=True)) == "look_assignment"


def test_route_after_storyboard_review_rejected_loops_back_to_director():
    """打回 → 回 storyboard_director 重新生成分镜(这条回环就是 Task 6 的核心)。"""
    assert g.route_after_storyboard_review(
        _base_state(storyboard_approved=False)) == "storyboard_director"


@pytest.mark.asyncio
async def test_storyboard_review_node_interrupts_and_records_rejection():
    """审核打回:记下人工意见 + 置 storyboard_revision_requested,供回环重生成参考。"""
    decision = {"approved": False, "notes": "重做前两镜"}
    with patch("drama_agent.workflow.graph.interrupt", return_value=decision):
        out = await g.storyboard_review_node(_base_state(shots=[{"shot_id": "s1"}]))
    assert out["storyboard_approved"] is False
    assert out["storyboard_revision_notes"] == "重做前两镜"
    assert out["current_stage"] == "storyboard_revision_requested"


@pytest.mark.asyncio
async def test_storyboard_review_node_approve_clears_notes():
    """通过时不带回历史打回意见 —— 否则重生成 prompt 会残留上一次的批注。"""
    with patch("drama_agent.workflow.graph.interrupt", return_value={"approved": True}):
        out = await g.storyboard_review_node(
            _base_state(shots=[{"shot_id": "s1"}], storyboard_revision_notes="旧意见"))
    assert out["storyboard_approved"] is True
    assert out["storyboard_revision_notes"] == ""


# ── 空造型不中断(Task 7)──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_look_review_skips_interrupt_when_no_assignments():
    """空指派时不得中断:UI 没有对应 resume 入口,中断会把剧集停死在 look_review。"""
    with patch("drama_agent.workflow.graph.interrupt") as m:
        out = await g.look_review_node(_base_state(look_assignments={}))
    m.assert_not_called()
    assert out["look_assignments_approved"] is True
    assert out["current_stage"] == "looks_approved"


@pytest.mark.asyncio
async def test_look_review_still_interrupts_when_assignments_exist():
    """有可指派造型时仍走人工审核中断(不能被空指派短路误伤)。"""
    with patch("drama_agent.workflow.graph.interrupt",
               return_value={"approved": True, "assignments": None}) as m:
        out = await g.look_review_node(_base_state(look_assignments={"1": {"林晓": "l1"}}))
    m.assert_called_once()
    assert out["look_assignments_approved"] is True
