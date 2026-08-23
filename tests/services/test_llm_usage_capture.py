"""usage 不再被丢:complete/complete_json 拿到 LLMResult 后必须记账。"""
import pytest
from unittest.mock import AsyncMock, patch

from drama_agent.provider.llm.protocols import LLMResult


@pytest.mark.asyncio
async def test_complete_records_usage():
    from drama_agent.services import llm_service as mod
    fake = LLMResult(text="hi", usage={"input": 12, "output": 3})
    with patch.object(mod.LLMService, "complete_result", AsyncMock(return_value=fake)), \
         patch.object(mod.usage_service, "record_llm", AsyncMock()) as rec:
        out = await mod.llm_service.complete("sys", "user", model="deepseek-v4-pro")
    assert out == "hi"
    rec.assert_awaited_once()
    assert rec.call_args.args[0] == {"input": 12, "output": 3}
    assert rec.call_args.kwargs["model"] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_complete_json_records_usage_once():
    """complete_json 走 complete_result,只记一次(不因内部再套 complete 而重复计费)。"""
    from drama_agent.services import llm_service as mod
    fake = LLMResult(text='{"k": 1}', usage={"input": 5, "output": 2})
    with patch.object(mod.LLMService, "complete_result", AsyncMock(return_value=fake)), \
         patch.object(mod.usage_service, "record_llm", AsyncMock()) as rec:
        out = await mod.llm_service.complete_json("sys", "user", model="deepseek-v4-pro")
    assert out == {"k": 1}
    rec.assert_awaited_once()
    assert rec.call_args.args[0] == {"input": 5, "output": 2}


@pytest.mark.asyncio
async def test_complete_records_empty_dict_when_usage_missing():
    """provider 未回 usage(None)时仍记一条(calls 计数),不因 None 崩。"""
    from drama_agent.services import llm_service as mod
    fake = LLMResult(text="x", usage=None)
    with patch.object(mod.LLMService, "complete_result", AsyncMock(return_value=fake)), \
         patch.object(mod.usage_service, "record_llm", AsyncMock()) as rec:
        out = await mod.llm_service.complete("sys", "user", model="deepseek-v4-pro")
    assert out == "x"
    assert rec.call_args.args[0] == {}
