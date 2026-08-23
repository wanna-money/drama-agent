"""LLM protocol 抽象 + OpenAI 兼容实现。

协议级差异(OpenAI vs Anthropic ...)→ 不同 Protocol 类;
同协议的厂商级差异(max_tokens 字段名等)→ compat 声明表。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from openai import AsyncOpenAI
from pydantic import BaseModel

from drama_agent.provider.base import Model, Provider
from drama_agent.services.retry import llm_retry


class LLMResult(BaseModel):
    """内部层返回:携带 usage 供后续计费统计。对外 LLMService.complete 仅取 .text。"""
    text: str
    usage: dict[str, int] | None = None   # {"input": N, "output": M}


class LLMProtocol(ABC):
    @abstractmethod
    async def complete(
        self,
        provider: Provider,
        model: Model,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        ...


class OpenAICompatProtocol(LLMProtocol):
    """OpenAI 兼容(chat.completions)。覆盖绝大多数国产/私有部署。

    compat 开关(默认对应标准 OpenAI):
      max_tokens_field: "max_tokens" | "max_completion_tokens"
    """

    def __init__(self, compat: dict | None = None):
        self.compat = compat or {}

    def _client(self, provider: Provider) -> AsyncOpenAI:
        api_key = provider.resolve_credential() or "placeholder"
        return AsyncOpenAI(api_key=api_key, base_url=provider.base_url or None)

    @llm_retry
    async def _create(self, client: AsyncOpenAI, **kwargs):
        return await client.chat.completions.create(**kwargs)

    async def complete(
        self,
        provider: Provider,
        model: Model,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        client = self._client(provider)
        max_tokens_field = self.compat.get("max_tokens_field", "max_tokens")
        kwargs: dict = {
            "model": model.id,
            "messages": messages,
            "temperature": temperature,
            max_tokens_field: max_tokens,
        }
        resp = await self._create(client, **kwargs)
        text = resp.choices[0].message.content or ""
        usage = None
        if getattr(resp, "usage", None):
            usage = {
                "input": getattr(resp.usage, "prompt_tokens", 0),
                "output": getattr(resp.usage, "completion_tokens", 0),
            }
        return LLMResult(text=text, usage=usage)


class OpenAIResponsesProtocol(LLMProtocol):
    """OpenAI Responses API(client.responses.create)。

    与 chat.completions 的差异:
      - system 类消息合并为 instructions;其余消息作为 input(role/content 列表)
      - token 上限用 max_output_tokens
      - 文本取 resp.output_text;usage 用 input_tokens/output_tokens
    """

    def _client(self, provider: Provider) -> AsyncOpenAI:
        api_key = provider.resolve_credential() or "placeholder"
        return AsyncOpenAI(api_key=api_key, base_url=provider.base_url or None)

    @llm_retry
    async def _create(self, client: AsyncOpenAI, **kwargs):
        return await client.responses.create(**kwargs)

    async def complete(
        self,
        provider: Provider,
        model: Model,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        client = self._client(provider)
        # system → instructions(合并多条);其余 → input(保留 role/content 结构)
        instructions = "\n\n".join(
            str(m.get("content", "")) for m in messages if m.get("role") == "system"
        ) or None
        input_items = [m for m in messages if m.get("role") != "system"]
        kwargs: dict = {
            "model": model.id,
            "input": input_items,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if instructions:
            kwargs["instructions"] = instructions
        resp = await self._create(client, **kwargs)
        text = getattr(resp, "output_text", "") or ""
        usage = None
        if getattr(resp, "usage", None):
            usage = {
                "input": getattr(resp.usage, "input_tokens", 0),
                "output": getattr(resp.usage, "output_tokens", 0),
            }
        return LLMResult(text=text, usage=usage)


# protocol key → 单例。新增协议在此登记(扩展点)。
_PROTOCOLS: dict[str, LLMProtocol] = {
    "openai-compat": OpenAICompatProtocol(),
    "openai-responses": OpenAIResponsesProtocol(),
}


def get_llm_protocol(key: str) -> LLMProtocol:
    proto = _PROTOCOLS.get(key)
    if proto is None:
        raise ValueError(f"Unknown LLM protocol: {key!r}")
    return proto
