"""Provider 适配层 · 注册表:三层合成(内置声明 → config 覆盖 → 冻结)+ 三跳解析。

registry 构建是启动期一次性、纯数据合成、不碰网络。构建失败只可能是 config 写错
(custom_providers 声明非法)→ 启动即报明确错误。
"""
from __future__ import annotations

import logging
from typing import Literal

from drama_agent.provider.base import Model, Provider, merge_providers

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """内置 Provider 声明 + config 的 custom_providers 覆盖,合成不可变解析表。"""

    def __init__(
        self,
        builtin: list[Provider],
        custom_providers: list[dict] | None = None,
    ):
        # config 的 custom_providers 是原始 dict;此处校验成 Provider(非法则抛,不静默吞)
        override: list[Provider] = [Provider(**d) for d in (custom_providers or [])]
        merged = merge_providers(builtin, override)
        self._providers: dict[str, Provider] = {p.id: p for p in merged}
        # model_id → (Provider, Model)。同 id 以后者为准(合并后 provider 内已按 id 去重)
        self._models: dict[str, tuple[Provider, Model]] = {}
        for p in merged:
            for m in p.models:
                self._models[m.id] = (p, m)
        self._converge_defaults()

    def _converge_defaults(self) -> None:
        """同 kind 全局至多一个 is_default:按遍历顺序留第一个,其余就地降级 + warning。
        只改 registry 内存副本,不回写 DB。"""
        seen: set[str] = set()
        for p in self._providers.values():
            for m in p.models:
                if not m.is_default:
                    continue
                if m.kind in seen:
                    m.is_default = False
                    logger.warning(
                        "Multiple default models for kind %r; keeping first, demoting %r.",
                        m.kind, m.id,
                    )
                else:
                    seen.add(m.kind)

    # ── 解析 ────────────────────────────────────────────────────────────
    def resolve_model(
        self, model: str, provider_hint: str | None = None
    ) -> tuple[Provider, Model]:
        """三跳解析入口。

        1) 命中已声明 model → (provider, model)
        2) provider 已知(provider_hint 或 "provider/model" 前缀)但 model 未声明
           → 造临时 fallback model + warning
        3) provider 都不认识 → raise ValueError
        """
        # 优先按字面 model id 精确匹配 —— 容许 id 本身含 '/'(如 deepseek-v4-flash-0731),
        if provider_hint is None and model in self._models:
            return self._models[model]

        # 支持 "provider/model_id" 形式显式指定 provider
        pid = provider_hint
        mid = model
        if pid is None and "/" in model:
            pid, mid = model.split("/", 1)

        if mid in self._models and pid is None:
            return self._models[mid]

        # 指定了 provider:命中该 provider 下的 model,否则 fallback
        if pid is not None:
            provider = self._providers.get(pid)
            if provider is None:
                raise ValueError(f"Unknown provider: {pid!r}")
            for m in provider.models:
                if m.id == mid:
                    return provider, m
            return provider, self._build_fallback_model(provider, mid)

        # 无 provider 提示、model 未声明 → 硬失败
        raise ValueError(
            f"Unknown model: {model!r}. Declare it in a built-in provider or "
            f"CUSTOM_PROVIDERS, or reference it as 'provider_id/{model}'."
        )

    def _build_fallback_model(self, provider: Provider, model_id: str) -> Model:
        """provider 已知但 model 未声明:基于该 provider 造临时 model(能力默认最小集)。"""
        logger.warning(
            "Model %r not declared under provider %r; using fallback declaration "
            "with default capabilities.",
            model_id, provider.id,
        )
        # 若 provider 有已声明 model,借第一个的 kind;否则默认 llm
        kind: Literal["llm", "video", "image"] = provider.models[0].kind if provider.models else "llm"
        return Model(id=model_id, label=model_id, provider=provider.id, kind=kind)

    def get_provider(self, provider_id: str) -> Provider:
        p = self._providers.get(provider_id)
        if p is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        return p

    # ── 目录查询 ────────────────────────────────────────────────────────
    def models(
        self,
        kind: Literal["llm", "video", "image"] | None = None,
        available_only: bool = False,
    ) -> list[Model]:
        """列出模型;kind 过滤类别;available_only 只返回凭证已配且已启用 provider 的模型。"""
        out: list[Model] = []
        for p in self._providers.values():
            if available_only and (not p.enabled or p.resolve_credential() is None):
                continue
            for m in p.models:
                if kind is None or m.kind == kind:
                    out.append(m)
        return out

    def default_model(self, kind: Literal["llm", "video", "image"]) -> Model | None:
        """该 kind 被标为 is_default 的模型;无则 None。已过构建期收敛,至多一个。"""
        for p in self._providers.values():
            for m in p.models:
                if m.kind == kind and m.is_default:
                    return m
        return None

    def effective_default(self, kind: Literal["llm", "video", "image"]) -> Model | None:
        """该 kind 的有效默认:is_default(default_model)优先,否则第一个可用(凭证已配)的模型;都无 → None。
        全站默认选取的唯一真相——前端与后端各兜底都收敛到此。"""
        dm = self.default_model(kind)
        if dm is not None:
            return dm
        avail = self.models(kind=kind, available_only=True)
        return avail[0] if avail else None

    def providers(self) -> list[Provider]:
        return list(self._providers.values())
