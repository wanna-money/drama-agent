"""全套测试的收尾:停掉 LangGraph checkpointer 的 aiosqlite 工作线程。

不停的话,整套测试跑完、结果都打印了,进程却卡住不返回 —— 那条线程是**非 daemon** 的,
而连接被 workflow.graph 的模块级单例一直持有,永不被 GC,threading._shutdown() 于是
永久 join 它(详见 workflow/graph.py:close_graphs)。

这里用同步的 conn.stop() 而不是 await close_graphs():session 收尾时创建该连接的事件
循环通常已经关了,close() 需要 loop,stop() 不需要(aiosqlite 正是为这个场景提供它的)。
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def stop_langgraph_checkpointer_thread():
    yield
    from drama_agent.workflow import graph
    conn, graph._checkpointer_conn = graph._checkpointer_conn, None
    graph._graph = None
    if conn is not None:
        conn.stop()
