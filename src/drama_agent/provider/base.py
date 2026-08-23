"""Provider 适配层 · 核心数据结构 + 凭证值语法 + 目录合并规则。

三维解耦:Provider(谁提供+凭证) × Protocol(怎么发请求,见 llm/video 子包) × Model(静态能力声明)。
本模块只放纯数据与纯函数,不碰网络、不依赖具体 protocol。
"""
from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel

# "$NAME" 或 "${NAME}" 的引用;NAME 为常见环境变量命名
_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$|^\$([A-Za-z_][A-Za-z0-9_]*)$")


def resolve_env(value: str | None) -> str | None:
    """解析凭证/头部值中的 $ENV / ${ENV} 引用。

    - "$NAME" / "${NAME}"  → 环境变量值;未设置返回 None(= 未配置)
    - "$$..."              → 字面 "$..."(转义)
    - 其他普通字符串        → 原样返回(明文兜底)
    - None                 → None
    """
    if value is None:
        return None
    if value.startswith("$$"):
        return value[1:]  # 去掉一个 $,得到字面量
    m = _ENV_REF.match(value)
    if m:
        name = m.group(1) or m.group(2)
        return os.environ.get(name)  # 未设置 → None
    return value


class Cost(BaseModel):
    """单价声明,用于后续用量/计费统计;先声明不强制填。"""
    input: float = 0        # 每百万 input token(LLM)
    output: float = 0       # 每百万 output token(LLM)
    cache_read: float = 0   # 命中缓存的 input(可选)
    per_call: float | None = None    # 每次生成(video)
    per_second: float | None = None  # 每秒时长(video)


class Model(BaseModel):
    """一个模型的静态声明(能力在 model 粒度)。"""
    id: str
    label: str
    provider: str                       # 归属 provider id
    kind: Literal["llm", "video", "image"]
    cost: Cost | None = None
    is_default: bool = False            # 该 kind 的默认模型(前端下拉预选);同 kind 全局最多一个,构建期收敛
    # —— LLM 能力 ——
    input: list[str] = ["text"]         # ["text","image"]
    reasoning: bool = False
    context_window: int | None = None
    max_tokens: int | None = None
    # —— video 能力 ——
    resolutions: list[str] = []
    default_resolution: str | None = None
    durations: list[int] = []
    aspect_ratios: list[str] = []
    supported_actions: list[str] = []   # rerun/regenerate/upscale
    supports_audio_reference: bool = False   # 是否支持参考音频(音色)
    max_reference_audios: int = 0            # 参考音频上限(按版本不同)
    # —— prompt 指南 ——
    prompt_guide_key: str | None = None   # → PROMPT_GUIDES 的键;prompt_engineer 按此取该模型的 prompting 指南


class Provider(BaseModel):
    """一个 provider 的声明 + 凭证;持有多个 model。"""
    id: str
    label: str
    protocol: str                       # → Protocol 实现 key
    base_url: str | None = None
    api_key: str | None = None          # 值支持 "$ENV" 引用
    headers: dict[str, str] = {}
    models: list[Model] = []
    enabled: bool = True                # 禁用的 provider 不进 registry(不可 resolve/调用)

    def resolve_credential(self) -> str | None:
        """解析 api_key 的 $ENV 引用;None 表示未配置。"""
        return resolve_env(self.api_key)

    def resolve_headers(self) -> dict[str, str]:
        """解析 headers 各值的 $ENV 引用;解析为 None 的项丢弃。"""
        out: dict[str, str] = {}
        for k, v in self.headers.items():
            rv = resolve_env(v)
            if rv is not None:
                out[k] = rv
        return out


def _merge_models(builtin: list[Model], override: list[Model]) -> list[Model]:
    """同 model id 替换、新 id 追加(保持 builtin 顺序,新增追加到末尾)。"""
    by_id: dict[str, Model] = {m.id: m for m in builtin}
    order = [m.id for m in builtin]
    for m in override:
        if m.id not in by_id:
            order.append(m.id)
        by_id[m.id] = m
    return [by_id[i] for i in order]


def _merge_one(base: Provider, ov: Provider) -> Provider:
    """字段级覆盖:ov 中非 None 字段盖过 base;models 单独按 id 合并。
    只给 base_url 不给 models(ov.models 为空)→ 保留 base.models(代理场景)。
    """
    merged = base.model_copy(deep=True)
    if ov.base_url is not None:
        merged.base_url = ov.base_url
    if ov.api_key is not None:
        merged.api_key = ov.api_key
    if ov.protocol:  # protocol 必填,给了就用 ov 的
        merged.protocol = ov.protocol
    if ov.label:
        merged.label = ov.label
    if ov.headers:
        merged.headers = {**merged.headers, **ov.headers}
    if ov.models:
        merged.models = _merge_models(base.models, ov.models)
    return merged


def merge_providers(
    builtin: list[Provider], override: list[Provider]
) -> list[Provider]:
    """三层合成的合并核心:同 provider id 字段级覆盖、新 id 追加。"""
    by_id: dict[str, Provider] = {p.id: p for p in builtin}
    order = [p.id for p in builtin]
    for ov in override:
        if ov.id in by_id:
            by_id[ov.id] = _merge_one(by_id[ov.id], ov)
        else:
            order.append(ov.id)
            by_id[ov.id] = ov
    return [by_id[i] for i in order]
