import base64
import binascii
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from drama_agent.db.session import get_db
from drama_agent.db.models import Project, Episode
from drama_agent.db.enums import (
    ImageType, LifecycleStatus, SERVABLE_IMAGE_TYPES, UPLOADABLE_IMAGE_TYPES,
)
from drama_agent.services import reference_service
from drama_agent.services.storage_service import storage_service
from drama_agent.services.public_storage import (
    PublicStorageUnavailable,
    get_public_storage,
)
from drama_agent.services.video_validate import validate_video, video_mime

# 图片(角色/背景参考图)按项目共享 → project 级路由
img_router = APIRouter(prefix="/api/projects", tags=["files"])
# 引用绑定 / 视频产物 → episode 级路由(引用存在每集图状态里,视频是每集产物)
router = APIRouter(prefix="/api/episodes", tags=["files"])

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _safe_path(base: Path, filename: str) -> Path:
    """Resolve path and ensure it stays within base dir (prevents path traversal)."""
    resolved = (base / filename).resolve()
    if not resolved.is_relative_to(base.resolve()):  # 真·子路径判断,避免 startswith 前缀绕过
        raise HTTPException(status_code=400, detail="Invalid filename")
    return resolved


async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


async def _get_episode_or_404(db: AsyncSession, episode_id: str) -> Episode:
    e = (await db.execute(select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Episode not found")
    return e


# ── 图片:项目级(角色/背景跨集共享) ─────────────────────────────────
@img_router.post("/{project_id}/files/upload")
async def upload_reference_image(
    project_id: str,
    file: UploadFile = File(...),
    type: str = Form(default="reference"),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(db, project_id)
    ext = Path(file.filename or "upload.jpg").suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
    image_type = type if type in UPLOADABLE_IMAGE_TYPES else ImageType.REFERENCE.value
    content = await file.read()
    unique_name, _ = await storage_service.save_project_image(
        project_id, content, file.filename or "upload.jpg", image_type
    )
    url = f"/api/projects/{project_id}/images/{image_type}/{unique_name}"
    return {"path": unique_name, "filename": unique_name, "url": url, "type": image_type}


class FromAssetRequest(BaseModel):
    asset_id: str
    type: str = "reference"


class FromBase64Request(BaseModel):
    """AI 生成的图落进项目参考目录。生成结果是 base64 在手,没有 File 可 multipart 上传。"""
    image_b64: str
    type: str = "reference"
    filename: str = "generated.png"


@img_router.post("/{project_id}/files/from-base64")
async def save_from_base64(
    project_id: str, req: FromBase64Request, db: AsyncSession = Depends(get_db)
):
    """把 base64 图片存进本项目参考目录。返回与 upload 同形状,前端走既有绑定流程。"""
    await _get_project_or_404(db, project_id)
    try:
        content = base64.b64decode(req.image_b64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=422, detail="image_b64 非法")
    if not content:
        raise HTTPException(status_code=422, detail="image_b64 为空")
    image_type = req.type if req.type in UPLOADABLE_IMAGE_TYPES else ImageType.REFERENCE.value
    unique_name, _ = await storage_service.save_project_image(
        project_id, content, req.filename or "generated.png", image_type
    )
    url = f"/api/projects/{project_id}/images/{image_type}/{unique_name}"
    return {"path": unique_name, "filename": unique_name, "url": url, "type": image_type}


@img_router.post("/{project_id}/files/from-asset")
async def copy_from_asset(
    project_id: str, req: FromAssetRequest, db: AsyncSession = Depends(get_db)
):
    """从全局素材库拷贝一张素材图进本项目参考目录(引用=拷贝快照)。返回与 upload 同形状,
    前端拿到 url 后走既有 updateReferences 绑定,下游参考流程零改。"""
    await _get_project_or_404(db, project_id)
    from drama_agent.services import asset_service
    asset = await asset_service.get_asset(req.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    content = await asset_service.read_asset_bytes(req.asset_id)
    if content is None:
        raise HTTPException(status_code=404, detail="素材文件不存在")
    image_type = req.type if req.type in UPLOADABLE_IMAGE_TYPES else ImageType.REFERENCE.value
    filename = (asset.name or "asset") + (Path(asset.storage_key).suffix or ".png")
    unique_name, _ = await storage_service.save_project_image(
        project_id, content, filename, image_type
    )
    url = f"/api/projects/{project_id}/images/{image_type}/{unique_name}"
    return {"path": unique_name, "filename": unique_name, "url": url, "type": image_type}


@img_router.post("/{project_id}/videos/upload")
async def upload_reference_video(
    project_id: str, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    """上传参考视频:存本地 + 传公网。

    **两份都要**:本地那份是长期可播的(平台直链 24 小时就失效),公网那份是给
    平台取的(视频参考只接受公网 URL,没有 base64 那条路)。只留一份的话,
    要么预览依赖外网,要么平台取不到。
    """
    await _get_project_or_404(db, project_id)
    content = await file.read()
    try:
        info = validate_video(content, file.filename or "")
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    try:
        storage = get_public_storage()
    except PublicStorageUnavailable as e:
        # 409 而非 500:这是"还没配置",用户能自己解决 —— 500 只会让人以为是故障
        raise HTTPException(
            409, f"上传参考视频需要先配置对象存储(存储管理):{e}") from None

    out_dir = storage_service.get_project_output_dir(project_id, "refvideos")
    local_name = f"{uuid.uuid4()}{Path(file.filename or 'a.mp4').suffix.lower()}"
    local_path = out_dir / local_name
    await storage_service.save_bytes(content, local_path)
    key = await storage.put(content, file.filename or "a.mp4")

    return {
        "storage_key": key,
        # 可直接取用的预览地址(相对 URL,前端拼在同源下)。
        # 不回服务器文件系统路径 —— 前端取不到,且泄露目录结构。
        "preview_url": f"/api/projects/{project_id}/videos/{local_name}/file",
        "duration": info["duration"],
        "warning": info["warning"],
    }


@img_router.get("/{project_id}/videos/{filename}/file")
async def serve_reference_video(
    project_id: str, filename: str, db: AsyncSession = Depends(get_db)
):
    """回上传的参考视频本体,供界面预览。

    与 `clips/{clip_id}/file` 同一形态:平台直链是预签名、会到期,
    本地落盘的这份才是长期可播的那份。
    """
    await _get_project_or_404(db, project_id)
    out_dir = storage_service.get_project_output_dir(project_id, "refvideos")
    path = _safe_path(out_dir, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(path, media_type=video_mime(filename), filename=filename)


@img_router.get("/{project_id}/images")
async def list_project_images(
    project_id: str, type: str | None = None, db: AsyncSession = Depends(get_db)
):
    await _get_project_or_404(db, project_id)
    images = await storage_service.list_project_images_async(project_id, type)
    return [
        {
            "filename": img["filename"], "type": img["type"], "size_bytes": img["size_bytes"],
            "url": f"/api/projects/{project_id}/images/{img['type']}/{img['filename']}",
        }
        for img in images
    ]


@img_router.get("/{project_id}/images/{image_type}/{filename}")
async def serve_project_image(project_id: str, image_type: str, filename: str):
    # 可读取的类型比可上传的多一个 keyframe(关键帧节点生成、不接受上传);
    # 用 SERVABLE 而非 UPLOADABLE 判断,否则关键帧图 URL 一律 400、缩略图必然坏掉。
    if image_type not in SERVABLE_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    image_dir = storage_service.get_project_image_dir(project_id, image_type)
    file_path = _safe_path(image_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


# ── 引用绑定:集级(存在每集图状态里) ───────────────────────────────
class ReferenceEntry(BaseModel):
    key: str
    ref_type: str        # ReferenceType(character/background),非法值 → 400
    image_url: str = ""  # 空串 = 已列出但未上传
    # 生成该图所用的 prompt(提炼后可人工改);重生成时改它而不是重新提炼
    prompt: str = ""
    # 角色实体关联(Character.id)。前端原样回传后端下发的值,不自己造。
    character_id: str | None = None


class UpdateReferencesRequest(BaseModel):
    references: list[ReferenceEntry]


async def _reference_source(db: AsyncSession, ep: Episode) -> dict:
    """凑出 reference_service 需要的读取源:已存清单 + 用于补占位的 story_analysis/shots。

    图状态(跑起来后最权威)覆盖 state_snapshot;created 态还没有图状态,则从源剧本借
    story_analysis —— 这样开拍前就能看到角色清单并预上传参考图。
    """
    source: dict = dict(ep.state_snapshot or {})
    if ep.status != LifecycleStatus.CREATED.value:
        try:
            from drama_agent.workflow.graph import get_graph
            graph = await get_graph()
            state = await graph.aget_state({"configurable": {"thread_id": ep.id}})
            if state and state.values:
                source.update(
                    {k: v for k, v in state.values.items() if v not in (None, [], {})}
                )
        except Exception:  # noqa: BLE001 — checkpointer 不可用时退回快照,不该让面板整体挂掉
            pass
    if not source.get("story_analysis") and ep.story_id:
        # 分析住在 Story 上(权威);经集的锚点直取,不绕 Script
        from drama_agent.services import story_service
        story = await story_service.row_of(db, ep.story_id)
        if story and story.story_analysis:
            source["story_analysis"] = story.story_analysis
    return source


@router.put("/{episode_id}/references")
async def update_references(
    episode_id: str, req: UpdateReferencesRequest, db: AsyncSession = Depends(get_db)
):
    """整表替换角色/背景参考图清单(前端每次提交完整列表),回写图状态与快照。

    ref_type 在此真正落地 —— 类型是后端持久化的权威,不再让前端按 key 反猜。
    """
    ep = await _get_episode_or_404(db, episode_id)
    try:
        references = reference_service.normalize(e.model_dump() for e in req.references)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if ep.status != LifecycleStatus.CREATED.value:
        try:
            from drama_agent.workflow.graph import get_graph
            graph = await get_graph()
            await graph.aupdate_state(
                {"configurable": {"thread_id": episode_id}}, {"references": references}
            )
        except Exception:  # noqa: BLE001 — 图不可写时仍落快照,下次启动由 runner 带回
            pass

    snapshot = dict(ep.state_snapshot or {})
    snapshot["references"] = references
    snapshot.pop("character_references", None)   # 旧字段已废弃,写入时顺手清掉
    ep.state_snapshot = snapshot
    await db.commit()
    return {"ok": True, "references": references}


@router.get("/{episode_id}/references")
async def get_references(episode_id: str, db: AsyncSession = Depends(get_db)):
    """完整参考图清单:已绑定的 + 探测出的未上传占位,每条带权威 ref_type。

    前端直接渲染本结果 —— 分组、占位、类型都不在前端算(规范 4)。
    """
    ep = await _get_episode_or_404(db, episode_id)
    source = await _reference_source(db, ep)
    return {"references": reference_service.build_list(source)}


# ── 视频产物:集级(每集输出目录 {project_id}/{episode_id}/) ─────────
@router.get("/{episode_id}/videos")
async def list_videos(episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = await _get_episode_or_404(db, episode_id)
    output_dir = storage_service.get_project_output_dir(ep.project_id, episode_id)
    videos = list(output_dir.glob("*.mp4"))
    return [
        {
            "filename": v.name,
            "url": f"/api/episodes/{episode_id}/files/{v.name}",
            "size_bytes": v.stat().st_size,
        }
        for v in videos if v.name != "final.mp4"
    ]


@router.get("/{episode_id}/files/{filename}")
async def download_file(episode_id: str, filename: str, db: AsyncSession = Depends(get_db)):
    ep = await _get_episode_or_404(db, episode_id)
    output_dir = storage_service.get_project_output_dir(ep.project_id, episode_id)
    file_path = _safe_path(output_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path))


@router.get("/{episode_id}/export")
async def export_final_video(episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = await _get_episode_or_404(db, episode_id)
    output_dir = storage_service.get_project_output_dir(ep.project_id, episode_id)
    final_path = output_dir / "final.mp4"
    if not final_path.exists():
        raise HTTPException(status_code=404, detail="Final video not yet assembled")
    return FileResponse(str(final_path), media_type="video/mp4", filename=f"drama_{episode_id}.mp4")
