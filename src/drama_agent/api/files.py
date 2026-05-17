from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pathlib import Path
from drama_agent.db.session import get_db
from drama_agent.db.models import Project
from drama_agent.services.storage_service import storage_service

router = APIRouter(prefix="/api/projects", tags=["files"])

ALLOWED_IMAGE_TYPES = {"character", "background", "reference"}
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _safe_path(base: Path, filename: str) -> Path:
    """Resolve path and ensure it stays within base dir (prevents path traversal)."""
    resolved = (base / filename).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return resolved


@router.post("/{project_id}/files/upload")
async def upload_reference_image(
    project_id: str,
    file: UploadFile = File(...),
    type: str = Form(default="reference"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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


class ReferenceEntry(BaseModel):
    key: str
    ref_type: str
    image_url: str


class UpdateReferencesRequest(BaseModel):
    references: list[ReferenceEntry]


@router.put("/{project_id}/references")
async def update_references(
    project_id: str,
    req: UpdateReferencesRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update character/background reference image bindings, writing back to LangGraph state."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    new_refs: dict[str, str] = {}
    for entry in req.references:
        if entry.image_url:
            new_refs[entry.key] = entry.image_url

    if project.status != "created":
        try:
            from drama_agent.workflow.graph import get_graph
            graph = await get_graph()
            config = {"configurable": {"thread_id": project_id}}
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

    snapshot = dict(project.state_snapshot or {})
    snapshot["character_references"] = new_refs
    project.state_snapshot = snapshot
    await db.commit()

    return {"ok": True, "character_references": new_refs}


@router.get("/{project_id}/references")
async def get_references(project_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    refs: dict[str, str] = {}
    if project.status != "created":
        try:
            from drama_agent.workflow.graph import get_graph
            graph = await get_graph()
            config = {"configurable": {"thread_id": project_id}}
            state = await graph.aget_state(config)
            if state and state.values:
                refs = state.values.get("character_references", {})
        except Exception:
            pass

    if not refs and project.state_snapshot:
        refs = project.state_snapshot.get("character_references", {})

    return {"character_references": refs}


@router.get("/{project_id}/images")
async def list_project_images(
    project_id: str,
    type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    images = await storage_service.list_project_images_async(project_id, type)
    return [
        {
            "filename": img["filename"],
            "type": img["type"],
            "size_bytes": img["size_bytes"],
            "url": f"/api/projects/{project_id}/images/{img['type']}/{img['filename']}",
        }
        for img in images
    ]


@router.get("/{project_id}/images/{image_type}/{filename}")
async def serve_project_image(project_id: str, image_type: str, filename: str):
    if image_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid image type")
    image_dir = storage_service.get_project_image_dir(project_id, image_type)
    file_path = _safe_path(image_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


@router.get("/{project_id}/files/{filename}")
async def download_file(project_id: str, filename: str):
    output_dir = storage_service.get_project_output_dir(project_id)
    file_path = _safe_path(output_dir, filename)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path))


@router.get("/{project_id}/videos")
async def list_videos(project_id: str):
    output_dir = storage_service.get_project_output_dir(project_id)
    videos = list(output_dir.glob("*.mp4"))
    return [
        {
            "filename": v.name,
            "url": f"/api/projects/{project_id}/files/{v.name}",
            "size_bytes": v.stat().st_size,
        }
        for v in videos
        if v.name != "final.mp4"
    ]


@router.get("/{project_id}/export")
async def export_final_video(project_id: str):
    output_dir = storage_service.get_project_output_dir(project_id)
    final_path = output_dir / "final.mp4"
    if not final_path.exists():
        raise HTTPException(status_code=404, detail="Final video not yet assembled")
    return FileResponse(str(final_path), media_type="video/mp4", filename=f"drama_{project_id}.mp4")
