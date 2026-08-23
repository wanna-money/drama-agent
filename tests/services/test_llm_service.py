"""Tests for LLM service (delegates to provider adapter layer)."""
import pytest
from unittest.mock import AsyncMock, patch
from drama_agent.services.llm_service import LLMService
from drama_agent.provider.llm.protocols import LLMResult


@pytest.fixture
def builtin_registry():
    """装一个含内置声明的 registry 单例(resolve_model 需要能解析内置 model)。
    registry 已收敛为仅从 env+DB 合成,单测里不跑 DB seed,故直接用代码内置声明构建。"""
    import drama_agent.provider as provider_pkg
    from drama_agent.provider.registry import ProviderRegistry
    orig = provider_pkg.provider_registry
    provider_pkg.provider_registry = ProviderRegistry(
        builtin=provider_pkg._builtin_providers(), custom_providers=[]
    )
    yield
    provider_pkg.provider_registry = orig


def _patch_protocol(content: str):
    """Patch the LLM protocol so complete() returns `content` without a real client."""
    return patch(
        "drama_agent.provider.llm.protocols.OpenAICompatProtocol.complete",
        new=AsyncMock(return_value=LLMResult(text=content)),
    )


@pytest.mark.asyncio
async def test_complete_json_strips_markdown_fences(builtin_registry):
    """complete_json should strip ```json ... ``` wrappers."""
    with _patch_protocol('```json\n{"key": "value"}\n```'):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="deepseek-v4-pro")
        assert result == {"key": "value"}


@pytest.mark.asyncio
async def test_complete_json_plain_json(builtin_registry):
    """complete_json should parse plain JSON without fences."""
    with _patch_protocol('{"name": "test", "count": 3}'):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="deepseek-v4-pro")
        assert result["name"] == "test"
        assert result["count"] == 3


@pytest.mark.asyncio
async def test_complete_json_invalid_json_returns_empty(builtin_registry):
    """complete_json should return {} when LLM returns malformed JSON."""
    with _patch_protocol('not valid json at all {{{}'):
        from drama_agent.services.llm_service import llm_service
        result = await llm_service.complete_json("system", "user", model="deepseek-v4-pro")
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
