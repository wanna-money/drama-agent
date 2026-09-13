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
from drama_agent.provider.ops import PROTOCOL_OPS, RESPONSE_FIELDS, ops_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])

# video protocol keys(由 video_service 工厂支持)
VIDEO_PROTOCOLS = ["seedance", "minimax"]


class ModelIn(BaseModel):
    """「模型管理」可编辑的模型字段。

    **必须与 provider/base.Model 的字段集保持一致**:这里缺一个字段,保存时
    `_models_json` 就把它从 models_json 里抹掉(而用户并没有改它)。
    代码独占、不给用户改的字段列在 provider/seed.CODE_OWNED_MODEL_FIELDS,
    由 seed 对账回填 —— 那些不该出现在这里。
    """
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
    min_duration: int = 0
    max_duration: int = 0
    default_aspect_ratio: str | None = None
    max_reference_videos: int = 0
    supports_omni_task_type: bool = False
    aspect_ratios: list[str] = []
    supported_actions: list[str] = []
    max_reference_images: int = 0
    forces_adaptive_ratio: bool = False
    supports_timestamp_prompt: bool = False
    supports_standalone_audio: bool = False
    max_reference_audios: int = 0
    supports_audio_reference: bool = False
    supports_seed: bool = False


class ProviderIn(BaseModel):
    provider_id: str
    label: str
    kind: str                       # "llm" | "video" | "image" | "storage"
    protocol: str
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool = True
    models: list[ModelIn] = []
    # 自定义接入路径 / 响应映射(见 provider/ops.py 的词表);留空 = 走协议官方默认。
    paths: dict[str, str] = {}
    response_map: dict[str, str] = {}
    # 后端专属配置(kind="storage":bucket/region/secret_id/prefix/expires_days)
    config: dict[str, str] = {}


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
    if kind == "storage":
        # 词表的权威是 public_storage 的注册表,不在此另抄一份(规范 4)
        from drama_agent.services.public_storage import _BACKEND_IMPLS
        return sorted(_BACKEND_IMPLS)
    return list(IMAGE_PROTOCOLS.keys())  # image


def _validate_access(body: ProviderIn) -> None:
    """校验自定义路径与响应映射的键。

    键名打错会静默失效(配了却不生效),比拒绝写入难查得多 —— 故在入口就按该 protocol
    认的词表拒掉;路径缺前导斜杠会与 base_url 拼出 `.../v1task/submit`,同样拒掉。
    """
    allowed_ops = ops_of(body.protocol)
    for op, path in body.paths.items():
        if op not in allowed_ops:
            raise HTTPException(
                422, f"功能键 {op!r} 不属于 protocol {body.protocol!r}"
                     f"(可用: {', '.join(allowed_ops) or '无'})")
        if not path.startswith("/"):
            raise HTTPException(422, f"路径 {path!r} 必须以 '/' 开头(与 base_url 直接拼接)")
    for field in body.response_map:
        if field not in RESPONSE_FIELDS:
            raise HTTPException(
                422, f"响应字段 {field!r} 未定义(可用: {', '.join(RESPONSE_FIELDS)})")


def _validate(body: ProviderIn) -> None:
    if not body.provider_id or "/" in body.provider_id:
        raise HTTPException(422, "provider_id 非空且不能包含 '/'")
    if body.kind not in ("llm", "video", "image", "storage"):
        raise HTTPException(422, "kind 必须是 llm / video / image / storage")
    if body.protocol not in _valid_protocols(body.kind):
        raise HTTPException(422, f"protocol {body.protocol!r} 未注册(kind={body.kind})")
    if body.kind == "storage":
        # 存储没有"功能键 → 路径"这回事,故跳过接入路径校验;
        # 它的配置在 config 里,由各后端自己解释。
        if body.models:
            raise HTTPException(422, "存储不持有模型,models 必须为空")
        from drama_agent.services.public_storage import _REQUIRED_CONFIG
        missing = [k for k in _REQUIRED_CONFIG.get(body.protocol, ())
                   if not body.config.get(k)]
        if missing:
            raise HTTPException(
                422, f"{body.protocol} 存储缺少必填配置: {', '.join(missing)}")
        return
    _validate_access(body)
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
        # 老库未 ALTER 出新列时降级为空,而不是让整个列表接口 500
        "paths": getattr(row, "paths_json", None) or {},
        "response_map": getattr(row, "response_map_json", None) or {},
        "config": getattr(row, "config_json", None) or {},
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
    """protocol 词表 + 每个 protocol 的功能键与官方默认路径。

    ops/response_fields 供前端渲染「自定义接入路径」表单(键名与 placeholder);
    词表是后端唯一真相,前端不另抄一份(规范 4)。
    """
    return {
        "llm": list(LLM_PROTOCOLS.keys()),
        "video": VIDEO_PROTOCOLS,
        "image": list(IMAGE_PROTOCOLS.keys()),
        "storage": _valid_protocols("storage"),
        "ops": PROTOCOL_OPS,
        "response_fields": RESPONSE_FIELDS,
    }


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
        api_key=body.api_key, models_json=_models_json(body),
        paths_json=dict(body.paths), response_map_json=dict(body.response_map),
        config_json=dict(body.config),
        enabled=body.enabled, builtin=False,
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
    # 整体覆盖(含清空):改回官方接入是常规操作,逐键合并会让清空无法表达
    row.paths_json = dict(body.paths)
    row.response_map_json = dict(body.response_map)
    # 整体覆盖(含清空):与 paths/response_map 同理
    row.config_json = dict(body.config)
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
