"""Provider 管理 CRUD。全部 provider 统一存 DB(api_key 明文,列表掩码);
内置(builtin=True,由 seed 种入)可改凭证/模型但不可删,自定义可增删改。
写操作后重建 registry(消费方动态查,立即生效)。"""
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent import provider as provider_pkg
from drama_agent.db.models import CustomProvider
from drama_agent.db.session import get_db
from drama_agent.provider.base import Cost, Model
from drama_agent.provider.llm.protocols import _PROTOCOLS as LLM_PROTOCOLS
from drama_agent.provider.image.protocols import _IMAGE_PROTOCOLS as IMAGE_PROTOCOLS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])

# video protocol keys(由 video_service 工厂支持)
VIDEO_PROTOCOLS = ["seedance", "minimax"]


class ModelIn(BaseModel):
    id: str
    label: str
    kind: str
    cost: Cost | None = None        # 单价声明,供成本估算;不填 → 该模型记为未定价
    is_default: bool = False        # 该 kind 的默认模型(下拉预选);同 kind 全局唯一由 registry 构建期收敛
    input: list[str] = ["text"]
    context_window: int | None = None
    max_tokens: int | None = None
    resolutions: list[str] = []
    default_resolution: str | None = None
    durations: list[int] = []
    aspect_ratios: list[str] = []
    supported_actions: list[str] = []


class ProviderIn(BaseModel):
    provider_id: str
    label: str
    kind: str                       # "llm" | "video" | "image"
    protocol: str
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    models: list[ModelIn] = []


def _models_json(body: ProviderIn) -> list[dict]:
    """把 ModelIn 转成完整 Model dict(补 provider 字段,使存库 JSON 可被 Model(**m) 复原)。"""
    return [{**m.model_dump(), "provider": body.provider_id} for m in body.models]


async def _clear_other_kind_defaults(
    db: AsyncSession, kind: str, keep_provider_id: str
) -> None:
    """全局单默认:清掉除 keep_provider_id 外、同 kind 其它 provider 的 is_default。
    在保存一个"带默认模型"的 provider 时调用,使"设为默认"真正全局生效、存库单一真相。"""
    rows = (await db.execute(
        select(CustomProvider).where(
            CustomProvider.kind == kind,
            CustomProvider.provider_id != keep_provider_id,
        )
    )).scalars().all()
    for r in rows:
        models = r.models_json or []
        new_models = [
            {**m, "is_default": False} if m.get("is_default") else m for m in models
        ]
        if new_models != models:
            r.models_json = new_models   # 重新赋新列表触发 JSON 列脏跟踪


def _mask(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 4:
        return "****"
    return "***" + key[-4:]


def _valid_protocols(kind: str) -> list[str]:
    if kind == "llm":
        return list(LLM_PROTOCOLS.keys())
    if kind == "video":
        return VIDEO_PROTOCOLS
    return list(IMAGE_PROTOCOLS.keys())  # image


def _validate(body: ProviderIn) -> None:
    if not body.provider_id or "/" in body.provider_id:
        raise HTTPException(422, "provider_id 非空且不能包含 '/'")
    if body.kind not in ("llm", "video", "image"):
        raise HTTPException(422, "kind 必须是 llm / video / image")
    if body.protocol not in _valid_protocols(body.kind):
        raise HTTPException(422, f"protocol {body.protocol!r} 未注册(kind={body.kind})")
    for m in body.models:
        if m.kind != body.kind:
            raise HTTPException(422, f"model {m.id!r} 的 kind 与 provider 不一致")
        try:
            Model(**{**m.model_dump(), "provider": body.provider_id})
        except Exception as e:
            raise HTTPException(422, f"model {m.id!r} 非法: {e}")


def _row_dict(row: CustomProvider, *, mask: bool) -> dict:
    return {
        "provider_id": row.provider_id,
        "label": row.label,
        "kind": row.kind,
        "protocol": row.protocol,
        "base_url": row.base_url,
        "api_key": _mask(row.api_key) if mask else row.api_key,
        "models": row.models_json or [],
        "builtin": row.builtin,
        "enabled": row.enabled,
    }


@router.get("")
async def list_providers(db: AsyncSession = Depends(get_db)):
    """全部 provider(内置 + 自定义)统一从 DB 读。api_key 一律掩码。"""
    rows = (await db.execute(select(CustomProvider))).scalars().all()
    return [_row_dict(r, mask=True) for r in rows]


@router.get("/protocols")
async def list_protocols():
    return {"llm": list(LLM_PROTOCOLS.keys()), "video": VIDEO_PROTOCOLS, "image": list(IMAGE_PROTOCOLS.keys())}


@router.get("/{provider_id}")
async def get_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    """返回真值 api_key(供编辑),内置与自定义一视同仁。"""
    row = (await db.execute(
        select(CustomProvider).where(CustomProvider.provider_id == provider_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Provider not found")
    return _row_dict(row, mask=False)


async def _rebuild_safe() -> None:
    try:
        await provider_pkg.rebuild_registry()
    except Exception as e:
        logger.warning("rebuild_registry after write failed; keeping old registry: %s", e)


@router.post("")
async def create_provider(body: ProviderIn, db: AsyncSession = Depends(get_db)):
    _validate(body)
    existing = (await db.execute(
        select(CustomProvider).where(CustomProvider.provider_id == body.provider_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"provider_id {body.provider_id!r} 已存在(请用 PUT 修改)")
    row = CustomProvider(
        id=str(uuid.uuid4()), provider_id=body.provider_id, label=body.label,
        protocol=body.protocol, kind=body.kind, base_url=body.base_url,
        api_key=body.api_key, models_json=_models_json(body), enabled=body.enabled, builtin=False,
    )
    db.add(row)
    if any(m.is_default for m in body.models):
        await _clear_other_kind_defaults(db, body.kind, body.provider_id)
    await db.commit()
    await _rebuild_safe()
    return _row_dict(row, mask=True)


@router.put("/{provider_id}")
async def update_provider(provider_id: str, body: ProviderIn, db: AsyncSession = Depends(get_db)):
    _validate(body)
    row = (await db.execute(
        select(CustomProvider).where(CustomProvider.provider_id == provider_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Provider not found")
    # 内置可改凭证/模型,但 provider_id / kind / builtin 不可变(kind 改动语义复杂);
    # 内置的 base_url 锁死官方地址(见 provider/*/providers.py),忽略请求里的覆盖。
    row.label = body.label
    row.protocol = body.protocol
    if not row.builtin:
        row.base_url = body.base_url
    row.api_key = body.api_key
    row.enabled = body.enabled
    row.models_json = _models_json(body)
    if any(m.is_default for m in body.models):
        await _clear_other_kind_defaults(db, row.kind, provider_id)
    await db.commit()
    await _rebuild_safe()
    return _row_dict(row, mask=True)


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(CustomProvider).where(CustomProvider.provider_id == provider_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Provider not found")
    if row.builtin:
        raise HTTPException(409, "内置 provider 不可删除")
    await db.delete(row)
    await db.commit()
    await _rebuild_safe()
    return {"ok": True}
