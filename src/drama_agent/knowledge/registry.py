"""知识层声明式接入:多后端按 kind 路由 + 全局兜底。与 provider/registry.py 同构。

接已有类型的库 = config knowledge_backends 加一条声明(零代码);
接全新协议 = 写实现 KnowledgeStore 协议的类 + BACKEND_TYPES 登记一行 + 声明。
降级(命中空 / 未认领 / 主后端抛)统一由本 registry 兜,后端只"检索或抛"。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:  # 仅类型;运行时不 import 后端类,避免 registry↔store↔dify_store 循环
    from drama_agent.knowledge.store import KnowledgeStore

logger = structlog.get_logger()


# 后端实例工厂:import 下沉到调用时(构建 registry 时)而非模块 import 时,
# 使 registry 模块顶层不牵连 store/dify_store —— 无论谁先被 import 都不成环。
def _make_constant(cfg: dict) -> "KnowledgeStore":
    from drama_agent.knowledge.store import ConstantKnowledgeStore
    return ConstantKnowledgeStore()


def _make_markdown(cfg: dict) -> "KnowledgeStore":
    from drama_agent.knowledge.store import MarkdownKnowledgeStore
    return MarkdownKnowledgeStore()


def _make_dify(cfg: dict) -> "KnowledgeStore":
    from drama_agent.knowledge.dify_store import DifyKnowledgeStore
    return DifyKnowledgeStore(**cfg)



class KnowledgeBackendDecl(BaseModel):
    id: str
    type: str
    kinds: list[str] = []
    fallback: bool = False
    config: dict = {}


BACKEND_TYPES: dict[str, Callable[[dict], "KnowledgeStore"]] = {
    "constant": _make_constant,
    "markdown": _make_markdown,
    "dify": _make_dify,
    # "pgvector": _make_pgvector,  # 实现后加工厂 + 登记
}


class KnowledgeRegistry:
    """按 kind 路由到主后端;未认领 / 命中空 / 主后端抛 → 全局兜底。自身实现 KnowledgeStore 协议。"""

    def __init__(self, decls: list[KnowledgeBackendDecl]):
        self._by_kind: dict[str, KnowledgeStore] = {}
        self._fallback: KnowledgeStore | None = None
        for d in decls:
            if d.type not in BACKEND_TYPES:
                raise ValueError(f"Unknown knowledge backend type: {d.type!r}")
            store = BACKEND_TYPES[d.type](d.config)
            for kind in d.kinds:
                if kind in self._by_kind:
                    raise ValueError(f"kind {kind!r} claimed by more than one backend")
                self._by_kind[kind] = store
            if d.fallback:
                if self._fallback is not None:
                    raise ValueError("multiple fallback backends declared")
                self._fallback = store
            if not d.fallback and not d.kinds:
                logger.warning("knowledge backend declares no kinds and is not fallback", id=d.id)

    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        primary = self._by_kind.get(kind)
        if primary is not None:
            try:
                out = primary.retrieve(kind, key, query, k)
            except Exception as e:  # noqa: BLE001 — 主后端失败回落兜底,可观测不静默
                logger.warning("knowledge primary backend failed, falling back",
                               kind=kind, error=str(e))
                out = []
            if out:
                return out
        if self._fallback is not None:
            return self._fallback.retrieve(kind, key, query, k)
        return []


def build_default_registry() -> KnowledgeRegistry:
    """显式 knowledge_backends 优先;否则从 dify_* settings 派生(复现现状、零回归)。"""
    from drama_agent.config import settings
    from drama_agent.knowledge.store import CRAFT_KINDS
    if settings.knowledge_backends:
        return KnowledgeRegistry(
            [KnowledgeBackendDecl(**d) for d in settings.knowledge_backends]
        )
    decls = [
        KnowledgeBackendDecl(id="craft", type="markdown", kinds=list(CRAFT_KINDS)),
        KnowledgeBackendDecl(id="base", type="constant", fallback=True),
    ]
    if settings.dify_base_url:
        decls.insert(0, KnowledgeBackendDecl(
            id="biz", type="dify",
            config={
                "base_url": settings.dify_base_url,
                "api_key": settings.dify_api_key,
                "dataset_ids": settings.dify_dataset_ids,
                "timeout": settings.knowledge_retrieve_timeout,
            },
            kinds=list(settings.dify_dataset_ids.keys()),
        ))
    return KnowledgeRegistry(decls)
