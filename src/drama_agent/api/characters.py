"""项目级角色 CRUD + 造型 + 三视图(上传/AI 生成)。文件走 AssetStorage 工厂。"""
import base64
import binascii
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.enums import CharacterView
from drama_agent.db.models import Project
from drama_agent.db.session import get_db
from drama_agent.services import audio_validate
from drama_agent.services import character_entity_service as svc
from drama_agent.services import character_gen_service
from drama_agent.services import character_import_service
from drama_agent.services.asset_storage import get_asset_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["characters"])

_VIEWS = {v.value for v in CharacterView}
ALLOWED_MIME = "image/"


def _char_dict(r) -> dict:
    # appearance(AI 抽的外貌)必须下发:角色页展示它,「生成形象」也用它当提示词。
    # 只回 description(人手写备注,通常为空)会让页面显示「—」,
    # 且生成的图完全丢掉外貌特征 —— 角色形象与剧本脱钩。
    return {"id": r.id, "project_id": r.project_id, "name": r.name,
            "description": r.description, "appearance": r.appearance,
            "voice_key": r.voice_key}


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
    # 整条 prompt 直给(如从剧本提炼后用户改过的)。给了就不再用 _sheet_prompt 拼 ——
    # 用户改过的措辞必须原样进模型,否则"可编辑"是假的。
    prompt: str | None = None


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
async def generate_sheet(
    pid: str, cid: str, lid: str, body: GenSheetIn, db: AsyncSession = Depends(get_db)
):
    """生成四视图 sheet 并尝试自动裁切。

    始终回传 sheet_b64(原图);自动裁切失败时 views=None,前端据此转人工裁切
    —— 生成本身是成功的,不该因为切不开而整体报错让用户重新烧一次生成。
    """
    char = await _verify_char(pid, cid)
    await _verify_look(pid, cid, lid)
    # appearance(AI 抽的外貌)优先:只退回 description/name 时,生成的图会丢掉外貌特征
    desc = body.character_desc or char.appearance or char.description or char.name
    look_desc = body.look_desc or ""
    # pid 已能定位作品,查它的 visual_style 传给 service —— 不需要前端多传字段。
    visual_style = (await db.execute(
        select(Project.visual_style).where(Project.id == pid))).scalar_one_or_none() or ""
    try:
        sheet, views = await character_gen_service.generate_four_view_sheet(
            desc, look_desc, body.model_id, prompt=body.prompt, visual_style=visual_style)
    except NotImplementedError as e:
        raise HTTPException(501, str(e) or "当前图片模型不支持生成")
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # noqa: BLE001 — 上游 4xx(尺寸/内容不合法)不该以 500 暴露
        # 500 在前端只显示 "Internal Server Error",用户看不到真正的原因
        # (实测:尺寸超上游比例上限时页面毫无反应)。透出上游 message 才可行动。
        # **必须留日志**:只把 message 转给前端而不记堆栈,排查时无从下手(自己踩过)。
        logger.warning("四视图生成失败 char=%s look=%s model=%s",
                       cid, lid, body.model_id, exc_info=True)
        raise HTTPException(502, f"图片生成失败: {str(e)[:300]}")
    enc = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {
        "sheet_b64": enc(sheet),
        "views": None if views is None else {
            "front": enc(views[0]), "side": enc(views[1]),
            "back": enc(views[2]), "face": enc(views[3]),
        },
    }


class CropSheetIn(BaseModel):
    sheet_b64: str


@router.post("/projects/{pid}/characters/{cid}/looks/{lid}/crop-sheet")
async def crop_sheet(pid: str, cid: str, lid: str, body: CropSheetIn):
    """把一张四视图 sheet 切开并填入 Look;切不开时 views=None 而非报错。

    与 generate-sheet 分开:生成与落库之间用户可以反复重新生成,只有他点保存的那张才该
    落库 —— 生成时顺带切会把中间弃用的那些也写进造型。
    """
    await _verify_char(pid, cid)
    await _verify_look(pid, cid, lid)
    try:
        content = base64.b64decode(body.sheet_b64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "sheet_b64 非法")
    try:
        views = character_gen_service.crop_four_views(content)
    except character_gen_service.CropFailed as e:
        # 生成本身是成功的,切不开只是没法自动填四视图 —— 回 200 带 views=None,
        # 让前端引导人工裁切;报 4xx 会让调用方以为整次生成失败而丢掉图。
        return {"views": None, "detail": str(e)}
    except UnidentifiedImageError:
        raise HTTPException(422, "图片无法解析")
    names = (CharacterView.FRONT.value, CharacterView.SIDE.value,
             CharacterView.BACK.value, CharacterView.FACE.value)
    row = None
    for view, content_i in zip(names, views):
        row = await svc.set_view(lid, view, content_i, f"{view}.png", "image/png")
        if row is None:
            raise HTTPException(404, "造型不存在")
    return {"views": _look_dict(row) if row else None}


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
    """从素材库人物 Asset 导入:切四视图填入 Look。

    错误分层:素材/造型不存在 → 404(数据问题);图片打不开或切不开 → 422(内容问题,
    前端据此引导人工裁切)。两者混成同一个码,前端就无从判断该不该弹裁切器。
    """
    await _verify_look(pid, cid, lid)
    try:
        row = await character_import_service.import_asset_as_look_views(lid, body.asset_id)
    except character_gen_service.CropFailed as e:
        raise HTTPException(422, str(e))
    except UnidentifiedImageError:
        raise HTTPException(422, "素材文件不是可识别的图片")
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
