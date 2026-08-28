"""协议层的原生工具调用:透传 tools、回读 tool_calls/finish_reason、不支持则抛错。

拦的是三类真实故障:tools 参数被吞、tool_calls/finish_reason 被丢弃(现状就是丢的)、
不支持工具的协议静默忽略 tools(与静默 return {} 同一类病)。
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from drama_agent.provider.base import Model, Provider
from drama_agent.provider.llm.protocols import (
    OpenAICompatProtocol, OpenAIResponsesProtocol,
)

TOOL = {
    "type": "function",
    "function": {
        "name": "read_scene",
        "description": "读取指定场次正文",
        "parameters": {
            "type": "object",
            "properties": {"scene_number": {"type": "integer"}},
            "required": ["scene_number"],
        },
    },
}


def _provider(protocol: str = "openai-compat") -> Provider:
    return Provider(id="p1", label="P", protocol=protocol,
                    base_url="http://example.invalid/v1", api_key="k", models=[])


def _model() -> Model:
    return Model(id="m1", label="M", provider="p1", kind="llm")


def _resp(*, content=None, tool_calls=None, finish_reason="stop", usage=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_call(cid: str, name: str, arguments: str):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=arguments))


@pytest.mark.asyncio
async def test_compat_forwards_tools_and_reads_tool_calls():
    """tools 要透传给 SDK,并把 tool_calls / finish_reason 原样带回来(现状全丢)。"""
    captured: dict = {}

    async def _fake_create(self, client, **kwargs):
        captured.update(kwargs)
        return _resp(
            content=None,
            tool_calls=[_tool_call("c1", "read_scene", '{"scene_number": 2}')],
            finish_reason="tool_calls",
        )

    with patch.object(OpenAICompatProtocol, "_create", _fake_create):
        result = await OpenAICompatProtocol().complete(
            _provider(), _model(), messages=[{"role": "user", "content": "第2场?"}],
            temperature=0.3, max_tokens=100, tools=[TOOL],
        )

    assert captured["tools"] == [TOOL]
    assert captured["tool_choice"] == "auto"
    assert result.finish_reason == "tool_calls"
    assert [(t.id, t.name, t.arguments) for t in result.tool_calls] == [
        ("c1", "read_scene", '{"scene_number": 2}')
    ]
    assert result.text == ""          # content 为 None 时归一成空串,调用方不必判 None


@pytest.mark.asyncio
async def test_compat_without_tools_sends_identical_request_body():
    """tools=None 时请求体不得多出 tools/tool_choice —— 否则给所有既有调用引入了变化。"""
    captured: dict = {}

    async def _fake_create(self, client, **kwargs):
        captured.update(kwargs)
        return _resp(content="hi")

    with patch.object(OpenAICompatProtocol, "_create", _fake_create):
        result = await OpenAICompatProtocol().complete(
            _provider(), _model(), messages=[{"role": "user", "content": "x"}],
            temperature=0.7, max_tokens=8000,
        )

    assert "tools" not in captured and "tool_choice" not in captured
    assert set(captured) == {"model", "messages", "temperature", "max_tokens"}
    assert result.text == "hi"
    assert result.tool_calls == []
    assert result.finish_reason == "stop"


@pytest.mark.asyncio
async def test_responses_protocol_rejects_tools_instead_of_dropping_them():
    """不支持工具的协议必须抛错,不能静默忽略 tools。"""
    with pytest.raises(ValueError, match="tool"):
        await OpenAIResponsesProtocol().complete(
            _provider("openai-responses"), _model(),
            messages=[{"role": "user", "content": "x"}],
            temperature=0.7, max_tokens=100, tools=[TOOL],
        )
