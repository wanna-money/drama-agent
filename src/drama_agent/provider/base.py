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


def dig(body: object, path: str) -> object | None:
    """按 "a.b.0.c" 取值:`.` 分层,纯数字段作数组下标。取不到返回 None。

    响应形态因网关而异(成片地址可能在 content.video_url,也可能在
    content.0.video_url.url),故取值路径要能声明而非写死。任务未完成时数组常为空,
    越界与穿透非容器都必须返回 None —— 抛异常会让轮询在中途炸掉。
    """
    if not path:
        return None
    cur: object = body
    for seg in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(seg)
        elif isinstance(cur, list) and seg.isdigit():
            idx = int(seg)
            cur = cur[idx] if idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


class ResponseShape:
    """按 provider 的 response_map 解析响应:字段取值路径 + 状态词归一。

    官方默认字段位置由各 protocol 实现传入,故 provider 只需声明与官方**不同**的那几项
    —— 为改一个路径而重抄整张映射表是不可接受的。两个 video provider 共用此类,
    避免各写一份解析(它们的差异只在默认位置)。
    """

    # wait_for_task 认的终态词表;网关的自有词(如 "success")必须归一到这里,
    # 否则轮询会一直当任务没结束、直到超时。
    CANONICAL_STATUSES = ("succeeded", "failed", "cancelled")

    def __init__(self, response_map: dict[str, str] | None, defaults: dict[str, str]):
        self._map = dict(response_map or {})
        self._defaults = dict(defaults)

    def get(self, body: object, name: str) -> object | None:
        path = self._map.get(name) or self._defaults.get(name)
        return dig(body, path) if path else None

    def status(self, raw: str) -> str:
        for canonical in self.CANONICAL_STATUSES:
            if raw == (self._map.get(f"status_{canonical}") or canonical):
                return canonical
        return raw


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
    # 单支时长的**闭区间**(秒)。平台给的是区间而非档位(如 Seedance 2.0 / MiniMax H3
    # 是 4-15、Seedance 2.5 是 4-30),故不要退回成 `durations: list[int]` 枚举清单 ——
    # 枚举会主动拒掉平台其实接受的值(如 7 秒),而"支持的时长为 [3,4,5,…]"这种
    # 错误信息比不校验更误导。0 / None 表示未声明该能力 → 不校验、前端用自己的兜底。
    min_duration: int = 0
    max_duration: int = 0
    aspect_ratios: list[str] = []
    default_aspect_ratio: str | None = None  # 建集时预选(短剧默认竖屏);空则由前端取首项
    supported_actions: list[str] = []   # rerun/regenerate/upscale
    supports_audio_reference: bool = False   # 是否支持参考音频(音色)
    max_reference_audios: int = 0            # 参考音频上限(按版本不同)
    # 参考图上限(按平台/版本不同)。声明在 model 而非实现类:界面要据此拦住超限提交,
    # 两处各持一份必然分叉(规范 4)。0 表示未声明 → 实现按自身默认。
    max_reference_images: int = 0
    # 参考视频上限。**0 即不支持** —— 这一个数字就是能力的完整表达,
    # 不另加 supports_video_ref 布尔位(同一事实的两份声明必然分叉)。
    # 前端据此决定「视频编辑/延长」两个模式是否渲染。
    max_reference_videos: int = 0
    # —— video 构造约束 ——
    # 平台对"某种输入组合下某参数必须取某值"的要求。**声明在 model 而非实现类**:
    # 这类约束按模型版本不同(如 Seedance 2.5 的首帧任务强制 adaptive 比例),
    # 写进实现类等于每出一个新版本改一次代码。判据:同一组字段、不同取值 → 这里;
    # 不同的字段集合 / 任务语义 → 另起一个 protocol。
    forces_adaptive_ratio: bool = False      # 有首帧/尾帧参考时,ratio 必须发 "adaptive"
    supports_timestamp_prompt: bool = False  # prompt 里的整数秒时间戳是否被响应
    supports_standalone_audio: bool = False  # 参考音频可否不搭配图片/视频单独输入
    # 能否显式声明子任务类型(omni_reference_task_type)。
    # **这一位不等于"能不能做编辑/延长"** —— 2.0 也能做,只是走平台的 auto 推断、
    # 没有提交时校验;声明了才在提交那一刻就把不兼容的参数拒掉。
    supports_omni_task_type: bool = False
    # 是否接受 seed 入参并回传实际取值。决定「重跑」能否真正复现同一支视频 ——
    # 不支持的模型上,重跑只是"再抽一次"(前端据此下发的能力提示,不在前端另判一次)。
    supports_seed: bool = False
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
    # 同一 protocol 被不同网关代理时,路径与响应形态**因部署而异**(请求体通常一致)。
    # 这类差异属于 provider(它的接入约定),不属于 protocol(怎么构造请求、什么业务语义)
    # —— 按网关拆 protocol 会退化成"一家一个 protocol",而它们的请求构造完全相同。
    # 两者留空即走该 protocol 的官方默认实现(含 SDK 内部路径),故接入行为零变化;
    # 判据是"有没有声明这个功能键",不是"是不是某一家网关"。
    paths: dict[str, str] = {}          # 功能键(如 video_submit)→ 相对路径
    response_map: dict[str, str] = {}   # 语义字段 → 该网关响应里的取值路径 / 状态词别名
    # 该 provider 的后端专属配置(storage kind 用:bucket/region/secret_id/prefix/
    # expires_days)。**不放 paths** —— 那一列的语义是"功能键 → 相对路径",且
    # `_validate_access` 按 PROTOCOL_OPS 词表严格校验键名,塞 bucket 进去会被拒。
    # 放宽那道校验等于削弱一处现有防线,故另立一格。
    config: dict[str, str] = {}

    def resolve_credential(self) -> str | None:
        """解析 api_key 的 $ENV 引用;None 表示未配置。"""
        return resolve_env(self.api_key)

    def path_for(self, op: str) -> str | None:
        """该功能键的自定义路径;未声明返回 None(调用方据此走官方默认实现)。"""
        return self.paths.get(op) or None

    def field_path(self, field: str, default: str) -> str:
        """该语义字段在响应里的取值路径;未声明则用协议默认。

        只需声明与官方**不同**的那几项,其余自动沿用默认。
        """
        return self.response_map.get(field) or default

    def status_word(self, canonical: str) -> str:
        """该网关表示某个规范状态的词(如 succeeded → success);未声明则原词。

        状态词表与取值路径同源但正交:只改了路径的网关不该被迫重抄一遍状态词。
        """
        return self.response_map.get(f"status_{canonical}") or canonical

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
    # 整体替换而非逐键合并:这两项是一份完整的接入声明,逐键合并会让"删掉某个自定义
    # 路径"变得无法表达(界面上清空一格,旧值仍从 base 渗回来)。空则保留 base。
    if ov.paths:
        merged.paths = dict(ov.paths)
    if ov.response_map:
        merged.response_map = dict(ov.response_map)
    if ov.config:
        merged.config = dict(ov.config)
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
