import pytest


@pytest.mark.asyncio
async def test_script_graph_only_writing_nodes():
    from drama_agent.workflow.graph import build_script_graph
    g = build_script_graph(checkpointer=None)
    nodes = set(g.get_graph().nodes)
    assert {"story_analyzer", "screenplay_writer", "screenplay_review",
            "screenplay_revision"} <= nodes
    assert "storyboard_director" not in nodes and "video_generator" not in nodes


@pytest.mark.asyncio
async def test_video_graph_starts_at_storyboard():
    from drama_agent.workflow.graph import build_video_graph
    g = build_video_graph(checkpointer=None)
    nodes = set(g.get_graph().nodes)
    assert {"storyboard_director", "look_assignment", "look_review", "prompt_engineer",
            "prompts_review", "keyframe_generator", "keyframes_review",
            "video_generator", "video_assembler"} <= nodes
    assert "story_analyzer" not in nodes and "screenplay_writer" not in nodes


def _edges(compiled) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in compiled.get_graph().edges}


@pytest.mark.asyncio
async def test_script_graph_review_routes_to_both_end_and_revision():
    """approved→END / rejected→revision 两支都必须在编译图上真实存在。

    路由函数返回字符串,LangGraph 无法静态推断分支;缺 path map 时会静默丢边。
    """
    from langgraph.graph import END
    from drama_agent.workflow.graph import build_script_graph
    edges = _edges(build_script_graph(checkpointer=None))
    assert ("screenplay_review", END) in edges
    assert ("screenplay_review", "screenplay_revision") in edges


@pytest.mark.asyncio
async def test_video_graph_downstream_reachable_from_start():
    """video_assembler 必须能从 START 走到 —— 条件边丢失会切断整条下游链。"""
    from drama_agent.workflow.graph import build_video_graph
    edges = _edges(build_video_graph(checkpointer=None))

    reachable, frontier = set(), ["__start__"]
    while frontier:
        cur = frontier.pop()
        for src, dst in edges:
            if src == cur and dst not in reachable:
                reachable.add(dst)
                frontier.append(dst)

    for node in ("prompt_engineer", "prompts_review", "keyframe_generator",
                 "keyframes_review", "video_generator", "video_assembler"):
        assert node in reachable, f"{node} unreachable from START; edges={sorted(edges)}"
