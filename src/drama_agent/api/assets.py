"""全局素材库 CRUD + 文件下发。文件走 AssetStorage 工厂(本地/CFS)。"""
import base64
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from drama_agent.db.enums import AssetCategory
from drama_agent.services import asset_gen_service, asset_service
from drama_agent.services.asset_storage import get_asset_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assets", tags=["assets"])

_CATEGORIES = {c.value for c in AssetCategory}
ALLOWED_MIME_PREFIX = "image/"


def _asset_dict(row) -> dict:
    return {
        "id": row.id,
        "category": row.category,
        "name": row.name,
        "description": row.description,
        "url": get_asset_storage().url_for(row.storage_key),
        "mime": row.mime,
        "size_bytes": row.size_bytes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _validate_category(category: str) -> None:
    if category not in _CATEGORIES:
        raise HTTPException(422, f"category 必须是 {sorted(_CATEGORIES)} 之一")


@router.get("")
async def list_assets(category: str | None = None):
    if category is not None:
        _validate_category(category)
    rows = await asset_service.list_assets(category)
    return [_asset_dict(r) for r in rows]


@router.post("")
async def create_asset(
    category: str = Form(...),
    name: str = Form(...),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
):
    _validate_category(category)
    if file.content_type and not file.content_type.startswith(ALLOWED_MIME_PREFIX):
        raise HTTPException(422, "只允许上传图片")
    content = await file.read()
    row = await asset_service.create_asset(
        category, name, description, content, file.filename or "upload.png", file.content_type
    )
    return _asset_dict(row)


@router.put("/{asset_id}")
async def update_asset(
    asset_id: str,
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
):
    content = await file.read() if file is not None else None
    filename = file.filename if file is not None else None
    mime = file.content_type if file is not None else None
    if file is not None and mime and not mime.startswith(ALLOWED_MIME_PREFIX):
        raise HTTPException(422, "只允许上传图片")
    row = await asset_service.update_asset(
        asset_id, name=name, description=description, content=content, filename=filename, mime=mime
    )
    if row is None:
        raise HTTPException(404, "素材不存在")
    return _asset_dict(row)


@router.delete("/{asset_id}")
async def delete_asset(asset_id: str):
    ok = await asset_service.delete_asset(asset_id)
    if not ok:
        raise HTTPException(404, "素材不存在")
    return {"ok": True}


@router.get("/file/{key}")
async def serve_asset_file(key: str):
    """本地 backend 的文件下发(CFS backend 时 url_for 直给对象 URL,不走这)。"""
    try:
        content = await get_asset_storage().read(key)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except NotImplementedError:
        raise HTTPException(400, "当前存储后端不支持本地下发")
    return Response(content=content, media_type="image/png")


# ── AI 生成/编辑(预览不落库;from-generated 落库)────────────────────────

class GenerateIn(BaseModel):
    model_id: str
    prompt: str
    size: str | None = None
    n: int = 1


class EditIn(BaseModel):
    asset_id: str
    model_id: str
    prompt: str
    size: str | None = None
    n: int = 1


class FromGeneratedIn(BaseModel):
    category: str
    name: str
    description: str | None = None
    image_b64: str


def _b64_images(images: list[bytes]) -> dict:
    return {"images": [base64.b64encode(b).decode() for b in images]}


@router.post("/generate")
async def generate_asset(body: GenerateIn):
    try:
        images = await asset_gen_service.generate_image(
            body.model_id, body.prompt, size=body.size, n=body.n
        )
    except NotImplementedError as e:
        raise HTTPException(501, str(e) or "当前图片模型不支持生成")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _b64_images(images)


@router.post("/edit")
async def edit_asset(body: EditIn):
    try:
        images = await asset_gen_service.edit_image(
            body.asset_id, body.model_id, body.prompt, size=body.size, n=body.n
        )
    except LookupError:
        raise HTTPException(404, "素材不存在")
    except NotImplementedError as e:
        raise HTTPException(501, str(e) or "当前图片模型不支持编辑")
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _b64_images(images)


@router.post("/from-generated")
async def create_from_generated(body: FromGeneratedIn):
    _validate_category(body.category)
    try:
        content = base64.b64decode(body.image_b64, validate=True)
    except ValueError:
        raise HTTPException(422, "image_b64 非法")
    row = await asset_service.create_asset(
        body.category, body.name, body.description, content, f"{body.name}.png", "image/png"
    )
    return _asset_dict(row)
