"""Tests for LLM service."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from drama_agent.services.llm_service import LLMService


def _make_mock_client(content: str):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = content
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_complete_json_strips_markdown_fences():
    """complete_json should strip ```json ... ``` wrappers."""
    mock_client = _make_mock_client('```json\n{"key": "value"}\n```')
    with patch("drama_agent.services.llm_service._resolve_client", return_value=(mock_client, "deepseek-v4-pro")):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="test-model")
        assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_complete_json_plain_json():
    """complete_json should parse plain JSON without fences."""
    mock_client = _make_mock_client('{"name": "test", "count": 3}')
    with patch("drama_agent.services.llm_service._resolve_client", return_value=(mock_client, "deepseek-v4-pro")):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="test-model")
        assert result["name"] == "test"
        assert result["count"] == 3


@pytest.mark.asyncio
async def test_complete_json_invalid_json_returns_empty():
    """complete_json should return {} when LLM returns malformed JSON."""
    mock_client = _make_mock_client('not valid json at all {{{}')
    with patch("drama_agent.services.llm_service._resolve_client", return_value=(mock_client, "deepseek-v4-pro")):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="test-model")
        assert result == {}


def test_parse_json_array():
    """_parse_json should handle JSON arrays."""
    result = LLMService._parse_json('[{"a": 1}, {"b": 2}]')
    assert result == [{"a": 1}, {"b": 2}]


def test_parse_json_with_preamble():
    """_parse_json should extract JSON even with leading text from LLM."""
    result = LLMService._parse_json('Here is the JSON:\n{"ok": true}')
    assert result == {"ok": True}


def test_parse_json_backtick_no_lang():
    """_parse_json should strip plain ``` fences."""
    result = LLMService._parse_json('```\n{"x": 42}\n```')
    assert result == {"x": 42}


def test_parse_json_invalid_returns_empty():
    """_parse_json should return {} for completely invalid input."""
    result = LLMService._parse_json('not json at all')
    assert result == {}
