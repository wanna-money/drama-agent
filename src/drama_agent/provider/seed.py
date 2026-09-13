"""内置 provider 声明 → DB(幂等 seed + 对账)。

代码里的内置声明(provider/llm|video|image/providers.py)是种子数据源,启动时对账 DB:
1. 缺失的内置 provider → 插入(builtin=True);首次插入 api_key 取 env 现值。
2. 已存在的内置 provider → 对齐 base_url(锁死、UI 只读)+ 回填**代码独有的能力字段**
   (见 CODE_OWNED_MODEL_FIELDS);api_key / enabled 与用户可改的模型字段一律不覆盖。
3. 声明里已删除的旧内置 provider(如下线的 bailian-video)→ 删除(内置 UI 删不掉,靠此清理)。
   仅动 builtin=True 的行;用户自定义(builtin=False)一律不碰。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

logger = logging.getLogger(__name__)

# 代码独占的模型能力字段:用户在「模型管理」里改不到它们(不在 api/providers.ModelIn 内),
# 权威只在代码声明。老库的 models_json 是旧版本代码写进去的,不回填的话新增能力对
# 已装机器**永远不可见** —— 声明了 supports_seed,接口下发的却是 False。
CODE_OWNED_MODEL_FIELDS = (
    "default_aspect_ratio",
    "supports_seed",
    "supports_audio_reference",
    "max_reference_audios",
    "prompt_guide_key",
    "reasoning",
    # 每新增一个能力字段都必须加进这里 —— 否则老库的 models_json 永不被回填,
    # 声明了 4-30 秒、接口下发的却是 0。
    "min_duration",
    "max_duration",
    "max_reference_images",
    "forces_adaptive_ratio",
    "supports_timestamp_prompt",
    "supports_standalone_audio",
    "max_reference_videos",
    "supports_omni_task_type",
)


# 用户可改、但**为空时**要用声明补上的列表字段:新增能力(如 aspect_ratios)在老库里是
# 空列表,不补的话前端下拉只剩兜底项;非空则是用户的选择,不动。
FILL_IF_EMPTY_MODEL_FIELDS = ("aspect_ratios", "resolutions", "supported_actions")


def _reconcile_models(stored: list[dict] | None, declared) -> list[dict] | None:
    """把代码独占能力字段回填进库里的 models_json;用户可改字段(label/cost/is_default/…)
    保持库里的值不动,仅当列表字段为空时用声明补上。声明里新增、库里还没有的 model
    追加到末尾 —— 插入判断是 provider 粒度的(见 seed_providers 第 1 步),给已有 provider
    新增一个模型不追加的话,该模型对已装机器永远不可见。返回新列表,或 None 表示无需改动。"""
    rows = list(stored or [])
    if not rows:
        return None
    by_id = {m.id: m for m in declared}
    out, changed = [], False
    for m in rows:
        decl = by_id.get(m.get("id"))
        if decl is None:            # 库里有、声明里没有的模型:用户加的,不动
            out.append(m)
            continue
        patch = {
            f: getattr(decl, f) for f in CODE_OWNED_MODEL_FIELDS
            if m.get(f) != getattr(decl, f)
        }
        patch.update({
            f: getattr(decl, f) for f in FILL_IF_EMPTY_MODEL_FIELDS
            if not m.get(f) and getattr(decl, f)
        })
        if patch:
            changed = True
            out.append({**m, **patch})
        else:
            out.append(m)
    # 内置 model 的权威在代码声明(见本函数 docstring),故声明有、库里没有的 model
    # 是新增的,不是用户删掉的 —— 追加进去。
    stored_ids = {m.get("id") for m in rows}
    for mid, decl in by_id.items():
        if mid not in stored_ids:
            out.append(decl.model_dump())
            changed = True
    return out if changed else None


async def seed_providers() -> int:
    """把代码内置声明幂等对账进 DB。返回新插入条数。

    无 DB / 表不存在 / 异常 → 记 warning 并返回已插入数(不阻断启动)。
    """
    from drama_agent import provider as provider_pkg
    from drama_agent.db import session as db_session
    from drama_agent.db.models import CustomProvider

    builtins = provider_pkg._builtin_providers()
    by_id = {p.id: p for p in builtins}
    builtin_ids = set(by_id)
    inserted = 0
    try:
        async with db_session.AsyncSessionLocal() as s:
            rows = (await s.execute(select(CustomProvider))).scalars().all()
            existing = {r.provider_id: r for r in rows}

            # 1) 插入缺失的内置 provider
            for p in builtins:
                if p.id in existing:
                    continue
                kind = p.models[0].kind if p.models else "llm"
                s.add(CustomProvider(
                    id=str(uuid.uuid4()),
                    provider_id=p.id,
                    label=p.label,
                    protocol=p.protocol,
                    kind=kind,
                    base_url=p.base_url,
                    api_key=p.resolve_credential(),  # env 现值(解析 $ENV / 明文)
                    models_json=[m.model_dump() for m in p.models],
                    enabled=p.enabled,
                    builtin=True,
                ))
                inserted += 1

            for r in rows:
                if not r.builtin:
                    continue  # 用户自定义 provider 一律不碰
                if r.provider_id not in builtin_ids:
                    # 3) 声明里已删除的旧内置(如 bailian-video)→ 清理
                    await s.delete(r)
                else:
                    decl = by_id[r.provider_id]
                    # 2) 对齐官方 base_url(锁死字段;不动 api_key/enabled)
                    if r.base_url != decl.base_url:
                        r.base_url = decl.base_url
                    # 回填代码独占的能力字段(用户改不到它们,声明是唯一权威)
                    merged = _reconcile_models(r.models_json, decl.models)
                    if merged is not None:
                        r.models_json = merged   # 重新赋新列表触发 JSON 列脏跟踪

            await s.commit()
    except Exception as e:  # noqa: BLE001 — seed 失败不应阻断启动
        logger.warning("seed_providers failed: %s", e)
    return inserted
