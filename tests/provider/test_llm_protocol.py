"""Task3 tests: OpenAICompatProtocol 的 compat 开关(测我们对协议差异的处理)+ 委派返回 text。
另含 OpenAIResponsesProtocol:测我们对 Responses API 的映射(messages→input/instructions、
output_text 提取、usage 字段映射、max_output_tokens)。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from drama_agent.provider.base import Model, Provider
from drama_agent.provider.llm.protocols import (
    OpenAICompatProtocol, OpenAIResponsesProtocol, LLMResult,
)


def _provider(compat=None):
    return Provider(id="t", label="t", protocol="openai-compat",
                    base_url="https://x/v1", api_key="sk-x",
                    models=[Model(id="tm", label="tm", provider="t", kind="llm")])


def _model():
    return Model(id="tm", label="tm", provider="t", kind="llm", max_tokens=4096)


def _mock_openai(content="hi", prompt_tokens=10, completion_tokens=5):
    client = MagicMock()
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    client.chat.completions.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_complete_returns_llmresult_with_text_and_usage():
    client = _mock_openai(content="hello")
    proto = OpenAICompatProtocol()
    with patch.object(proto, "_client", return_value=client):
        result = await proto.complete(_provider(), _model(),
                                      messages=[{"role": "user", "content": "hi"}],
                                      temperature=0.7, max_tokens=8000)
    assert isinstance(result, LLMResult)
    assert result.text == "hello"
    assert result.usage == {"input": 10, "output": 5}


@pytest.mark.asyncio
async def test_compat_uses_max_completion_tokens_when_declared():
    """compat.max_tokens_field='max_completion_tokens' → 请求用该字段名,而非 max_tokens。"""
    client = _mock_openai()
    proto = OpenAICompatProtocol(compat={"max_tokens_field": "max_completion_tokens"})
    with patch.object(proto, "_client", return_value=client):
        await proto.complete(_provider(), _model(),
                             messages=[{"role": "user", "content": "hi"}],
                             temperature=0.5, max_tokens=1234)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs.get("max_completion_tokens") == 1234
    assert "max_tokens" not in kwargs


@pytest.mark.asyncio
async def test_compat_default_uses_max_tokens():
    client = _mock_openai()
    proto = OpenAICompatProtocol()  # 默认
    with patch.object(proto, "_client", return_value=client):
        await proto.complete(_provider(), _model(),
                             messages=[{"role": "user", "content": "hi"}],
                             temperature=0.5, max_tokens=999)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs.get("max_tokens") == 999
    assert "max_completion_tokens" not in kwargs


# ── OpenAIResponsesProtocol(Responses API 映射)────────────────────────────

def _mock_responses(output_text="hi", input_tokens=12, output_tokens=7):
    client = MagicMock()
    resp = MagicMock()
    resp.output_text = output_text          # 真实字符串,避免 MagicMock 被判 truthy
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    client.responses.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_responses_returns_text_and_maps_usage():
    client = _mock_responses(output_text="hello", input_tokens=12, output_tokens=7)
    proto = OpenAIResponsesProtocol()
    with patch.object(proto, "_client", return_value=client):
        result = await proto.complete(_provider(), _model(),
                                      messages=[{"role": "user", "content": "hi"}],
                                      temperature=0.7, max_tokens=8000)
    assert isinstance(result, LLMResult)
    assert result.text == "hello"
    assert result.usage == {"input": 12, "output": 7}  # input_tokens/output_tokens 映射


@pytest.mark.asyncio
async def test_responses_uses_max_output_tokens_not_max_tokens():
    client = _mock_responses()
    proto = OpenAIResponsesProtocol()
    with patch.object(proto, "_client", return_value=client):
        await proto.complete(_provider(), _model(),
                             messages=[{"role": "user", "content": "hi"}],
                             temperature=0.5, max_tokens=1500)
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs.get("max_output_tokens") == 1500
    assert "max_tokens" not in kwargs and "messages" not in kwargs


@pytest.mark.asyncio
async def test_responses_splits_system_to_instructions_and_input():
    """system 合并进 instructions;其余消息作为 input(role/content 列表)。"""
    client = _mock_responses()
    proto = OpenAIResponsesProtocol()
    with patch.object(proto, "_client", return_value=client):
        await proto.complete(_provider(), _model(), messages=[
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": "你好"},
        ], temperature=0.5, max_tokens=500)
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs.get("instructions") == "你是助手"
    assert kwargs.get("input") == [{"role": "user", "content": "你好"}]  # system 不进 input


@pytest.mark.asyncio
async def test_responses_no_system_omits_instructions():
    client = _mock_responses()
    proto = OpenAIResponsesProtocol()
    with patch.object(proto, "_client", return_value=client):
        await proto.complete(_provider(), _model(),
                             messages=[{"role": "user", "content": "hi"}],
                             temperature=0.5, max_tokens=500)
    kwargs = client.responses.create.call_args.kwargs
    assert "instructions" not in kwargs  # 无 system 时不传该字段
