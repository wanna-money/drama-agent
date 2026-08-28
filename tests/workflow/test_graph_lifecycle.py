"""图单例的生命周期:checkpointer 连接必须能被关掉。

拦的是一类真实事故而非定义:aiosqlite 的连接工作线程是**非 daemon** 线程,而连接被
graph 模块的单例一直持有 → 永不被 GC → Connection.__del__ 那条兜底 stop() 永不执行,
于是解释器退出时 threading._shutdown() 永久 join 它,进程再也不退出:
  · pytest:整套跑完、结果都打印了却卡住不返回
  · uvicorn --reload:旧子进程收到信号也不死,继续占着端口和 checkpoint db,
    请求可能被这个事件循环已停的僵尸接走 → 表现为"后端整体无响应"
"""
import asyncio
import threading

import pytest

from drama_agent.workflow import graph as g


def _worker_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if "_connection_worker_thread" in (t.name or "")]


async def _wait_until(pred, timeout: float = 3.0) -> bool:
    """轮询等条件成立 —— 工作线程是收到 sentinel 后自行 break,退出不是同步的。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


@pytest.fixture
async def isolated_graph_module(tmp_path, monkeypatch):
    """把 checkpointer 指到临时库,并在用例前后保证模块单例是干净的。"""
    monkeypatch.setattr(g.settings, "langgraph_db_path", str(tmp_path / "cp.db"))
    saved = (g._graph, g._checkpointer_conn)
    g._graph = g._checkpointer_conn = None
    yield
    await g.close_graphs()
    g._graph, g._checkpointer_conn = saved


@pytest.mark.asyncio
async def test_close_graphs_stops_the_checkpointer_worker_thread(isolated_graph_module):
    """关图必须真的把那条非 daemon 工作线程停掉,否则进程退不出去(见模块 docstring)。"""
    before = len(_worker_threads())
    await g.init_graphs()
    assert len(_worker_threads()) == before + 1, "init_graphs 应当开出一条连接工作线程"

    await g.close_graphs()
    assert await _wait_until(lambda: len(_worker_threads()) == before), \
        "close_graphs 之后仍有 aiosqlite 工作线程存活 —— 进程将卡在 threading._shutdown"


@pytest.mark.asyncio
async def test_close_graphs_is_idempotent_and_clears_singletons(isolated_graph_module):
    """重复关不能炸(lifespan 异常路径 / 测试收尾都可能多调一次),且单例要清干净,
    以便之后还能重新 init(测试里会反复 init/close)。"""
    await g.init_graphs()
    await g.close_graphs()
    await g.close_graphs()
    assert g._graph is None
    assert g._checkpointer_conn is None

    await g.init_graphs()          # 关掉之后仍可重新初始化
    assert g._graph is not None


@pytest.mark.asyncio
async def test_init_graphs_is_idempotent_and_does_not_leak_a_second_connection(
    isolated_graph_module,
):
    """重复 init 不能每次都开一条新连接/重建图 —— 旧连接会失去引用者、线程永远留着。"""
    await g.init_graphs()
    n = len(_worker_threads())
    first_conn, first_graph = g._checkpointer_conn, g._graph
    await g.init_graphs()
    assert len(_worker_threads()) == n, "重复 init_graphs 泄漏了额外的连接工作线程"
    assert g._checkpointer_conn is first_conn
    assert g._graph is first_graph, "重复 init_graphs 重建了图单例"


@pytest.mark.asyncio
async def test_app_lifespan_closes_the_checkpointer(monkeypatch, tmp_path):
    """真正兜住事故的是 lifespan 收尾里那一次 close_graphs —— 少了它,线上/本地
    每次重启都会留下一个占着端口和 checkpoint db 的僵尸进程。"""
    from drama_agent.main import lifespan

    called: list[str] = []
    monkeypatch.setattr(g, "init_graphs", _noop(called, "init"))
    monkeypatch.setattr(g, "close_graphs", _noop(called, "close"))
    monkeypatch.setattr("drama_agent.db.session.init_db", _noop(called, "init_db"))
    monkeypatch.setattr("drama_agent.provider.seed.seed_providers", _noop(called, "seed"))
    monkeypatch.setattr("drama_agent.provider.rebuild_registry", _noop(called, "registry"))

    class _Worker:
        def __init__(self, **_kw): pass
        async def run_forever(self): await asyncio.sleep(3600)
        async def stop(self): called.append("worker_stop")

    monkeypatch.setattr("drama_agent.main.JobWorker", _Worker)
    monkeypatch.setattr("drama_agent.main.init_db", _noop(called, "init_db"))

    class _App:
        class state:  # noqa: N801 — 只需属性容器
            pass

    async with lifespan(_App()):
        pass
    assert "close" in called, "lifespan 退出时没有关闭 checkpointer 连接"
    # 图要在 worker 停下之后再关(worker 正在用它)
    assert called.index("worker_stop") < called.index("close")


def _noop(sink: list[str], tag: str):
    async def _f(*_a, **_kw):
        sink.append(tag)
    return _f
