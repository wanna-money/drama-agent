from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from drama_agent.db.session import get_db
from drama_agent.db.models import Project, Episode
from drama_agent.db.enums import LifecycleStatus
from drama_agent.services.storage_service import storage_service

# 图片(角色/背景参考图)按项目共享 → project 级路由
img_router = APIRouter(prefix="/api/projects", tags=["files"])
# 引用绑定 / 视频产物 → episode 级路由(引用存在每集图状态里,视频是每集产物)
router = APIRouter(prefix="/api/episodes", tags=["files"])

ALLOWED_IMAGE_TYPES = {"character", "background", "reference"}
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
    image_type = type if type in ALLOWED_IMAGE_TYPES else "reference"
    content = await file.read()
    unique_name, _ = await storage_service.save_project_image(
        project_id, content, file.filename or "upload.jpg", image_type
    )
    url = f"/api/projects/{project_id}/images/{image_type}/{unique_name}"
    return {"path": unique_name, "filename": unique_name, "url": url, "type": image_type}


class FromAssetRequest(BaseModel):
    asset_id: str
    type: str = "reference"


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
    image_type = req.type if req.type in ALLOWED_IMAGE_TYPES else "reference"
    filename = (asset.name or "asset") + (Path(asset.storage_key).suffix or ".png")
    unique_name, _ = await storage_service.save_project_image(
        project_id, content, filename, image_type
    )
    url = f"/api/projects/{project_id}/images/{image_type}/{unique_name}"
    return {"path": unique_name, "filename": unique_name, "url": url, "type": image_type}


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
    if image_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    image_dir = storage_service.get_project_image_dir(project_id, image_type)
    file_path = _safe_path(image_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


# ── 引用绑定:集级(存在每集图状态里) ───────────────────────────────
class ReferenceEntry(BaseModel):
    key: str
    ref_type: str
    image_url: str


class UpdateReferencesRequest(BaseModel):
    references: list[ReferenceEntry]


@router.put("/{episode_id}/references")
async def update_references(
    episode_id: str, req: UpdateReferencesRequest, db: AsyncSession = Depends(get_db)
):
    """更新角色/背景参考图绑定,回写到该集 LangGraph 状态。"""
    ep = await _get_episode_or_404(db, episode_id)

    new_refs: dict[str, str] = {}
    for entry in req.references:
        if entry.image_url:
            new_refs[entry.key] = entry.image_url

    if ep.status != LifecycleStatus.CREATED.value:
        try:
            from drama_agent.workflow.graph import get_video_graph
            graph = await get_video_graph()
            config = {"configurable": {"thread_id": episode_id}}
            state = await graph.aget_state(config)
            if state and state.values:
                existing = dict(state.values.get("character_references", {}))
                existing.update(new_refs)
                cleared = {e.key for e in req.references if not e.image_url}
                for k in cleared:
                    existing.pop(k, None)
                await graph.aupdate_state(config, {"character_references": existing})
                new_refs = existing
        except Exception:
            pass

    snapshot = dict(ep.state_snapshot or {})
    snapshot["character_references"] = new_refs
    ep.state_snapshot = snapshot
    await db.commit()
    return {"ok": True, "character_references": new_refs}


@router.get("/{episode_id}/references")
async def get_references(episode_id: str, db: AsyncSession = Depends(get_db)):
    ep = await _get_episode_or_404(db, episode_id)
    refs: dict[str, str] = {}
    if ep.status != LifecycleStatus.CREATED.value:
        try:
            from drama_agent.workflow.graph import get_video_graph
            graph = await get_video_graph()
            config = {"configurable": {"thread_id": episode_id}}
            state = await graph.aget_state(config)
            if state and state.values:
                refs = state.values.get("character_references", {})
        except Exception:
            pass
    if not refs and ep.state_snapshot:
        refs = ep.state_snapshot.get("character_references", {})
    return {"character_references": refs}


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
