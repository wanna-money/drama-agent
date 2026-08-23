import pytest
from unittest.mock import patch
import httpx


@pytest.fixture
def builtin_registry():
    """装含内置声明的 registry 单例(resolve_model 需能解析内置 model)。"""
    import drama_agent.provider as provider_pkg
    from drama_agent.provider.registry import ProviderRegistry
    orig = provider_pkg.provider_registry
    provider_pkg.provider_registry = ProviderRegistry(
        builtin=provider_pkg._builtin_providers(), custom_providers=[]
    )
    yield
    provider_pkg.provider_registry = orig


@pytest.mark.asyncio
async def test_llm_complete_retries_on_429(builtin_registry):
    """LLM 调用命中 429 应按我们的 retry 配置重试(重试逻辑在 protocol._create)。"""
    from drama_agent.services.llm_service import LLMService
    from drama_agent.provider.llm.protocols import OpenAICompatProtocol
    svc = LLMService()
    calls = 0

    class FakeResp:
        choices = [type("C", (), {"message": type("M", (), {"content": "hi"})()})()]
        usage = None

    async def fake_create(**kwargs):
        nonlocal calls
        calls += 1
        if calls < 2:
            raise httpx.HTTPStatusError(
                "rate", request=httpx.Request("POST", "http://x"),
                response=httpx.Response(429))
        return FakeResp()

    fake_client = type("Cli", (), {})()
    fake_client.chat = type("Chat", (), {})()
    fake_client.chat.completions = type("Comp", (), {"create": staticmethod(fake_create)})()

    # 用真实内置 model(deepseek-v4-pro);仅替换 protocol 底层 client,retry 装饰器照常生效
    with patch.object(OpenAICompatProtocol, "_client", return_value=fake_client):
        out = await svc.complete("s", "u", model="deepseek-v4-pro")
    assert out == "hi" and calls == 2

