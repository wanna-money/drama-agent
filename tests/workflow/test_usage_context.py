import asyncio
import pytest


@pytest.mark.asyncio
async def test_context_propagates_to_child_task():
    from drama_agent.workflow.usage_context import set_usage_context, current_usage_context
    set_usage_context(entity_id="e1", project_id="p1", is_script=False, node="screenplay_writer")

    async def child():
        return current_usage_context()

    # 子任务继承创建时的 contextvar 快照(节点内并发场景,如 asyncio.gather)
    ctx = await asyncio.create_task(child())
    assert ctx == {"entity_id": "e1", "project_id": "p1", "is_script": False, "node": "screenplay_writer"}


def test_context_none_or_dict_by_default():
    from drama_agent.workflow.usage_context import current_usage_context
    # 未 set 时返回 None(或被其他测试污染成 dict);只验证类型语义,不误判
    v = current_usage_context()
    assert v is None or isinstance(v, dict)
