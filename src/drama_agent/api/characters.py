"""项目级角色 CRUD + 造型 + 三视图(上传/AI 生成)。文件走 AssetStorage 工厂。"""
import base64

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from drama_agent.db.enums import CharacterView
from drama_agent.services import audio_validate
from drama_agent.services import character_entity_service as svc
from drama_agent.services import character_gen_service
from drama_agent.services import character_import_service
from drama_agent.services.asset_storage import get_asset_storage

router = APIRouter(prefix="/api", tags=["characters"])

_VIEWS = {v.value for v in CharacterView}
ALLOWED_MIME = "image/"


def _char_dict(r) -> dict:
    return {"id": r.id, "project_id": r.project_id, "name": r.name,
            "description": r.description, "voice_key": r.voice_key}


def _look_dict(r) -> dict:
    return {"id": r.id, "character_id": r.character_id, "name": r.name,
            "is_default": r.is_default, "front_key": r.front_key,
            "side_key": r.side_key, "back_key": r.back_key, "face_key": r.face_key}


async def _verify_char(pid: str, cid: str):
    """校验角色 cid 属于项目 pid;不匹配一律 404(防跨项目越权/误操作)。"""
    char = await svc.get_character(cid)
    if char is None or char.project_id != pid:
        raise HTTPException(404, "角色不存在")
    return char


async def _verify_look(pid: str, cid: str, lid: str):
    """校验造型 lid 属于角色 cid、且 cid 属于项目 pid。"""
    await _verify_char(pid, cid)
    look = await svc.get_look(lid)
    if look is None or look.character_id != cid:
        raise HTTPException(404, "造型不存在")
    return look


class CharacterIn(BaseModel):
    name: str
    description: str | None = None


class LookIn(BaseModel):
    name: str = "默认造型"
    is_default: bool = False


class LookUpdate(BaseModel):
    name: str | None = None
    is_default: bool | None = None


class GenSheetIn(BaseModel):
    model_id: str
    character_desc: str | None = None
    look_desc: str | None = None


class ViewsFromGenerated(BaseModel):
    front_b64: str
    side_b64: str | None = None
    back_b64: str | None = None
    face_b64: str | None = None


class ImportFromAsset(BaseModel):
    asset_id: str


@router.get("/projects/{pid}/characters")
async def list_characters(pid: str):
    return [_char_dict(r) for r in await svc.list_characters(pid)]


@router.post("/projects/{pid}/characters")
async def create_character(pid: str, body: CharacterIn):
    return _char_dict(await svc.create_character(pid, body.name, body.description))


@router.put("/projects/{pid}/characters/{cid}")
async def update_character(pid: str, cid: str, body: CharacterIn):
    await _verify_char(pid, cid)
    row = await svc.update_character(cid, name=body.name, description=body.description)
    if row is None:
        raise HTTPException(404, "角色不存在")
    return _char_dict(row)


@router.delete("/projects/{pid}/characters/{cid}")
async def delete_character(pid: str, cid: str):
    await _verify_char(pid, cid)
    if not await svc.delete_character(cid):
        raise HTTPException(404, "角色不存在")
    return {"ok": True}


@router.get("/projects/{pid}/characters/{cid}/looks")
async def list_looks(pid: str, cid: str):
    await _verify_char(pid, cid)
    return [_look_dict(r) for r in await svc.list_looks(cid)]


@router.post("/projects/{pid}/characters/{cid}/looks")
async def create_look(pid: str, cid: str, body: LookIn):
    await _verify_char(pid, cid)
    return _look_dict(await svc.create_look(cid, body.name, body.is_default))


@router.put("/projects/{pid}/characters/{cid}/looks/{lid}")
async def update_look(pid: str, cid: str, lid: str, body: LookUpdate):
    await _verify_look(pid, cid, lid)
    row = await svc.update_look(lid, name=body.name, is_default=body.is_default)
    if row is None:
        raise HTTPException(404, "造型不存在")
    return _look_dict(row)


@router.delete("/projects/{pid}/characters/{cid}/looks/{lid}")
async def delete_look(pid: str, cid: str, lid: str):
    await _verify_look(pid, cid, lid)
    if not await svc.delete_look(lid):
        raise HTTPException(404, "造型不存在")
    return {"ok": True}


@router.post("/projects/{pid}/characters/{cid}/looks/{lid}/views/{view}")
async def upload_view(pid: str, cid: str, lid: str, view: str, file: UploadFile = File(...)):
    await _verify_look(pid, cid, lid)
    if view not in _VIEWS:
        raise HTTPException(422, f"view 必须是 {sorted(_VIEWS)} 之一")
    if file.content_type and not file.content_type.startswith(ALLOWED_MIME):
        raise HTTPException(422, "只允许上传图片")
    content = await file.read()
    row = await svc.set_view(lid, view, content, file.filename or "view.png", file.content_type)
    if row is None:
        raise HTTPException(404, "造型不存在")
    return _look_dict(row)


@router.post("/projects/{pid}/characters/{cid}/looks/{lid}/generate-sheet")
async def generate_sheet(pid: str, cid: str, lid: str, body: GenSheetIn):
    char = await _verify_char(pid, cid)
    await _verify_look(pid, cid, lid)
    desc = body.character_desc or char.description or char.name
    look_desc = body.look_desc or ""
    try:
        front, side, back, face = await character_gen_service.generate_four_view_sheet(
            desc, look_desc, body.model_id)
    except NotImplementedError as e:
        raise HTTPException(501, str(e) or "当前图片模型不支持生成")
    except ValueError as e:
        raise HTTPException(422, str(e))
    enc = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"views": {"front": enc(front), "side": enc(side), "back": enc(back),
                      "face": enc(face)}}


@router.post("/projects/{pid}/characters/{cid}/looks/{lid}/views-from-generated")
async def views_from_generated(pid: str, cid: str, lid: str, body: ViewsFromGenerated):
    await _verify_look(pid, cid, lid)
    pairs = [(CharacterView.FRONT.value, body.front_b64),
             (CharacterView.SIDE.value, body.side_b64),
             (CharacterView.BACK.value, body.back_b64),
             (CharacterView.FACE.value, body.face_b64)]
    row = None
    for view, b64 in pairs:
        if not b64:
            continue
        try:
            content = base64.b64decode(b64, validate=True)
        except ValueError:
            raise HTTPException(422, f"{view} base64 非法")
        row = await svc.set_view(lid, view, content, f"{view}.png", "image/png")
        if row is None:
            raise HTTPException(404, "造型不存在")
    if row is None:
        raise HTTPException(422, "至少提供一张视图")
    return _look_dict(row)


@router.post("/projects/{pid}/characters/{cid}/looks/{lid}/import-from-asset")
async def import_from_asset(pid: str, cid: str, lid: str, body: ImportFromAsset):
    """从素材库人物 Asset 导入:切四视图填入 Look。"""
    await _verify_look(pid, cid, lid)
    try:
        row = await character_import_service.import_asset_as_look_views(lid, body.asset_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if row is None:
        raise HTTPException(404, "造型不存在")
    return _look_dict(row)


@router.get("/characters/view/{key}")
async def serve_view(key: str):
    try:
        content = await get_asset_storage().read(key)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except NotImplementedError:
        raise HTTPException(400, "当前存储后端不支持本地下发")
    return Response(content=content, media_type="image/png")


@router.post("/projects/{pid}/characters/{cid}/voice")
async def upload_voice(pid: str, cid: str, file: UploadFile = File(...)):
    await _verify_char(pid, cid)
    content = await file.read()
    try:
        audio_validate.validate_audio(content, file.filename or "voice.wav", file.content_type)
    except ValueError as e:
        raise HTTPException(422, str(e))
    row = await svc.set_voice(cid, content, file.filename or "voice.wav", file.content_type)
    if row is None:
        raise HTTPException(404, "角色不存在")
    return _char_dict(row)


@router.delete("/projects/{pid}/characters/{cid}/voice")
async def delete_voice(pid: str, cid: str):
    await _verify_char(pid, cid)
    row = await svc.clear_voice(cid)
    if row is None:
        raise HTTPException(404, "角色不存在")
    return _char_dict(row)


@router.get("/characters/voice/{key}")
async def serve_voice(key: str):
    try:
        content = await get_asset_storage().read(key)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except NotImplementedError:
        raise HTTPException(400, "当前存储后端不支持本地下发")
    return Response(content=content, media_type=audio_validate.audio_mime(key))
