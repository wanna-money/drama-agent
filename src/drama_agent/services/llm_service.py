"""LLM 服务:薄封装,委派给 provider 适配层(registry 解析 + protocol 调用)。

不再按模型名前缀硬编码路由;model → provider → protocol 三跳解析。
对外 complete() 仍返回纯 str(现有节点调用签名不变)。
"""
import json
import re

from drama_agent import provider as provider_pkg
from drama_agent.provider.llm.protocols import LLMResult, get_llm_protocol
from drama_agent.services import usage_service


def _provider_id(model: str | None) -> str:
    """记账用的 provider 名(仅展示,不参与成本计算)。解析失败不阻断主流程。"""
    if not model:
        return ""
    try:
        prov, _ = provider_pkg.provider_registry.resolve_model(model)
        return prov.id
    except Exception:  # noqa: BLE001 — 记账旁路,provider 名缺失可接受
        return ""


class LLMService:
    async def complete_result(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> LLMResult:
        """完整结果(含 usage),供计费统计;内部层。"""
        if not model:
            raise ValueError("model must be specified")
        # 动态查 registry,便于测试重绑
        registry = provider_pkg.provider_registry
        prov, mdl = registry.resolve_model(model)
        protocol = get_llm_protocol(prov.protocol)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return await protocol.complete(
            prov, mdl, messages=messages,
            temperature=temperature, max_tokens=8000,
        )

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        """简单补全,返回文本(对外层,拆包 LLMResult.text + 记账)。"""
        result = await self.complete_result(system, user, temperature=temperature, model=model)
        await usage_service.record_llm(
            result.usage or {}, provider=_provider_id(model), model=model or ""
        )
        return result.text

    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> dict:
        """补全并解析 JSON,剥离可能的 markdown 围栏。"""
        system_with_json = (
            system + "\n\nRespond ONLY with valid JSON. No markdown, no explanation."
        )
        result = await self.complete_result(
            system_with_json, user, temperature=temperature, model=model
        )
        await usage_service.record_llm(
            result.usage or {}, provider=_provider_id(model), model=model or ""
        )
        return self._parse_json(result.text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        fence = re.match(r"^```(?:json)?\s*\n?([\s\S]*?)\n?```$", text)
        if fence:
            text = fence.group(1).strip()
        start = min(
            (text.find(c) for c in ('{', '[') if text.find(c) != -1),
            default=0,
        )
        end_brace = text.rfind('}')
        end_bracket = text.rfind(']')
        end = max(end_brace, end_bracket) + 1
        if end > start:
            text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}


llm_service = LLMService()
