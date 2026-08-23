import aiofiles
import httpx
import uuid
from pathlib import Path
from drama_agent.config import settings


class StorageService:
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.output_dir = Path(settings.output_dir)

    def _ensure_dirs(self):
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_project_output_dir(self, project_id: str, episode_id: str | None = None) -> Path:
        d = self.output_dir / project_id
        if episode_id:
            d = d / episode_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_project_image_dir(self, project_id: str, image_type: str = "reference") -> Path:
        # 参考图按项目共享(角色跨集),不按集分层
        d = self.upload_dir / project_id / image_type
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def save_upload(self, content: bytes, filename: str) -> str:
        """Save uploaded file, return relative path."""
        self._ensure_dirs()
        ext = Path(filename).suffix
        unique_name = f"{uuid.uuid4()}{ext}"
        path = self.upload_dir / unique_name
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        return str(path)

    async def save_project_image(self, project_id: str, content: bytes, filename: str, image_type: str = "reference") -> tuple[str, str]:
        """Save image under project directory, return (unique_filename, absolute_path)."""
        image_dir = self.get_project_image_dir(project_id, image_type)
        ext = Path(filename).suffix or ".jpg"
        unique_name = f"{uuid.uuid4()}{ext}"
        path = image_dir / unique_name
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        return unique_name, str(path)

    def list_project_images(self, project_id: str, image_type: str | None = None) -> list[dict]:
        """List images for a project, optionally filtered by type. Sync version for non-async callers."""
        results = []
        base = self.upload_dir / project_id
        if not base.exists():
            return results
        types = [image_type] if image_type else ["character", "background", "reference"]
        for t in types:
            type_dir = base / t
            if not type_dir.exists():
                continue
            for f in sorted(type_dir.iterdir()):
                if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                    results.append({
                        "filename": f.name,
                        "type": t,
                        "path": str(f),
                        "size_bytes": f.stat().st_size,
                    })
        return results

    async def list_project_images_async(self, project_id: str, image_type: str | None = None) -> list[dict]:
        """Async wrapper to avoid blocking the event loop."""
        import asyncio
        return await asyncio.to_thread(self.list_project_images, project_id, image_type)

    async def download_file(self, url: str, dest_path: Path) -> str:
        """Stream-download a remote file to dest_path, return local path string."""
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async with aiofiles.open(dest_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                        await f.write(chunk)
        return str(dest_path)

    async def save_bytes(self, content: bytes, dest_path: Path) -> str:
        async with aiofiles.open(dest_path, "wb") as f:
            await f.write(content)
        return str(dest_path)


storage_service = StorageService()
