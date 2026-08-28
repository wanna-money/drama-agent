"""统一图上的边:条件边的 path map 丢了会静默切边,编译期不报错。

只保留两条真会放走回归的断言 —— 审核分支两支都在、下游链从 START 可达。
节点清单本身不测(那是复述定义);分流入口在 test_graph_routing.py。
"""
import pytest


def _edges(compiled) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in compiled.get_graph().edges}


def _reachable_from(edges: set[tuple[str, str]], start: str) -> set[str]:
    reachable, frontier = set(), [start]
    while frontier:
        cur = frontier.pop()
        for src, dst in edges:
            if src == cur and dst not in reachable:
                reachable.add(dst)
                frontier.append(dst)
    return reachable


@pytest.mark.asyncio
async def test_screenplay_review_routes_to_storyboard_and_revision():
    """approved→storyboard_director / rejected→revision 两支都必须在编译图上真实存在。

    路由函数返回字符串,LangGraph 无法静态推断分支;缺 path map 时会静默丢边。
    通过时**不能**再连 END:那是剧本图与剧集图合并前的接线(那时剧本通过即结束),
    残留它会让"从故事开始"的集在剧本通过后原地终止,永远到不了分镜/视频。
    """
    from langgraph.graph import END
    from drama_agent.workflow.graph import build_unified_graph
    edges = _edges(build_unified_graph(checkpointer=None))
    assert ("screenplay_review", "storyboard_director") in edges
    assert ("screenplay_review", "screenplay_revision") in edges
    assert ("screenplay_review", END) not in edges


@pytest.mark.asyncio
async def test_storyboard_review_routes_to_look_and_back_to_director():
    """分镜审核:通过→look_assignment / 打回→storyboard_director,两支都得在编译图上。

    这条回环(review 打回后回到 director 重做)是 Task 6 的核心;缺 path map 会静默丢边,
    表现为"打回分镜"永远无效或直接卡死。
    """
    from drama_agent.workflow.graph import build_unified_graph
    edges = _edges(build_unified_graph(checkpointer=None))
    assert ("storyboard_director", "storyboard_review") in edges
    assert ("storyboard_review", "look_assignment") in edges
    assert ("storyboard_review", "storyboard_director") in edges


@pytest.mark.asyncio
async def test_whole_pipeline_reachable_from_start():
    """从 START 必须能走到成片 —— 合并成一张图后,剧本段与制作段之间断一条边
    就会让"从故事开始"的集永远到不了分镜/视频,而编译期毫无提示。

    只从 START 走拦不住那种断裂:条件入口自带一条 START→storyboard_director 的
    "复用剧本"边,制作段借它照样可达。所以再单独从 story_analyzer 起走一遍。
    """
    from drama_agent.workflow.graph import build_unified_graph
    edges = _edges(build_unified_graph(checkpointer=None))

    reachable = _reachable_from(edges, "__start__")

    for node in ("story_analyzer", "screenplay_writer", "screenplay_review",
                 "storyboard_director", "storyboard_review", "look_assignment", "look_review",
                 "prompt_engineer", "prompts_review", "keyframe_generator",
                 "keyframes_review", "video_generator", "video_assembler"):
        assert node in reachable, f"{node} unreachable from START; edges={sorted(edges)}"

    from_story = _reachable_from(edges, "story_analyzer")
    for node in ("screenplay_review", "storyboard_director", "storyboard_review",
                 "prompt_engineer", "video_generator", "video_assembler"):
        assert node in from_story, (
            f"{node} unreachable from story_analyzer —— 「从故事开始」这条流断在剧本段; "
            f"edges={sorted(edges)}"
        )
