"""Provider 适配层公共入口:模块级 registry 单例 + 动态重建。

registry 的全部 provider 来自 config.CUSTOM_PROVIDERS(env)叠加 DB(优先级最高)。
内置 provider(kimi/glm/…)不再直接进 registry —— 它们由 provider/seed.py 幂等种入
DB(builtin=True),启动后与自定义 provider 一样从 DB 读。
业务侧动态查 `provider_pkg.provider_registry`(可被测试/重建重绑)。

- 模块导入时同步构建(仅 env,不碰 DB;import 期无 event loop)。
- lifespan 启动先 seed_providers()、再 rebuild_registry()(async)折入 DB provider 并
  重赋值单例。所有消费方动态查单例 → 立即生效,零改。
"""
from __future__ import annotations

import logging

from drama_agent.config import settings
from drama_agent.provider.base import Cost, Model, Provider, resolve_env
from drama_agent.provider.llm.providers import builtin_llm_providers
from drama_agent.provider.registry import ProviderRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "Cost", "Model", "Provider", "resolve_env",
    "ProviderRegistry", "provider_registry", "build_registry", "rebuild_registry",
]


def _builtin_providers() -> list[Provider]:
    builtin: list[Provider] = list(builtin_llm_providers())
    try:
        from drama_agent.provider.video.providers import builtin_video_providers
        builtin += list(builtin_video_providers())
    except ImportError:
        pass
    try:
        from drama_agent.provider.image.providers import builtin_image_providers
        builtin += list(builtin_image_providers())
    except ImportError:
        pass
    return builtin


def build_registry(db_providers: list[Provider] | None = None) -> ProviderRegistry:
    """全部 provider 来自 env CUSTOM_PROVIDERS + DB(seed 后含内置)。

    内置声明不再直接进 registry —— 它是 seed 的种子(见 provider/seed.py)。
    builtin 传空列表,merge_providers([], override) 退化为 override 全量按 id 去重。
    override 列表按追加顺序生效(后者覆盖前者同 id):env 先、DB 后 → DB 最高。
    """
    env_override: list[Provider] = [Provider(**d) for d in (settings.custom_providers or [])]
    override = env_override + list(db_providers or [])
    # ProviderRegistry 接收原始 dict(env)或已构建 Provider;统一转 dict 让其校验一致处理
    override_dicts = [p.model_dump() for p in override]
    return ProviderRegistry(builtin=[], custom_providers=override_dicts)


async def rebuild_registry() -> ProviderRegistry:
    """重读 DB 自定义 provider + 重新合成 + 重赋值模块级单例。写操作后调用。"""
    global provider_registry
    from drama_agent.provider.custom_store import load_custom_providers
    db_providers = await load_custom_providers()
    provider_registry = build_registry(db_providers=db_providers)
    return provider_registry


# 模块级单例(import 期同步构建:内置 + env,不含 DB)。
provider_registry = build_registry()
