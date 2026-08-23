"""素材库存储工厂:抽象 AssetStorage + 本地/CFS 后端。仅素材库用(不碰现有 storage_service)。

扩展:新增后端 = 加一个 AssetStorage 子类 + 在 _BACKENDS 登记一条。
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from pathlib import Path

import aiofiles

from drama_agent.config import settings


class AssetStorage(ABC):
    @abstractmethod
    async def save(self, content: bytes, filename: str) -> str:
        """存文件,返回 storage_key(后端内相对标识)。"""

    @abstractmethod
    async def read(self, key: str) -> bytes:
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...

    @abstractmethod
    def url_for(self, key: str) -> str:
        """前端可访问的 URL。"""


class LocalAssetStorage(AssetStorage):
    """本地目录(settings.asset_local_dir)。key = "<uuid>.<ext>";
    url_for → /api/assets/file/<key>(API 静态下发)。"""

    def __init__(self) -> None:
        self.root = Path(settings.asset_local_dir)

    def _path(self, key: str) -> Path:
        # key 只允许基础名(save 生成),防目录穿越
        return self.root / Path(key).name

    async def save(self, content: bytes, filename: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        ext = Path(filename).suffix or ".png"
        key = f"{uuid.uuid4()}{ext}"
        async with aiofiles.open(self.root / key, "wb") as f:
            await f.write(content)
        return key

    async def read(self, key: str) -> bytes:
        async with aiofiles.open(self._path(key), "rb") as f:
            return await f.read()

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def url_for(self, key: str) -> str:
        return f"/api/assets/file/{key}"


class CfsAssetStorage(AssetStorage):
    """生产 CFS / 对象存储 —— 预留 stub。接入时实现各方法并在 .env 切 asset_storage_backend=cfs。"""

    async def save(self, content: bytes, filename: str) -> str:
        raise NotImplementedError("CfsAssetStorage 尚未实现(生产接入时补)")

    async def read(self, key: str) -> bytes:
        raise NotImplementedError("CfsAssetStorage 尚未实现(生产接入时补)")

    async def delete(self, key: str) -> None:
        raise NotImplementedError("CfsAssetStorage 尚未实现(生产接入时补)")

    def url_for(self, key: str) -> str:
        raise NotImplementedError("CfsAssetStorage 尚未实现(生产接入时补)")


_BACKENDS: dict[str, type[AssetStorage]] = {
    "local": LocalAssetStorage,
    "cfs": CfsAssetStorage,
}


def get_asset_storage() -> AssetStorage:
    """按 settings.asset_storage_backend 选后端(默认 local)。"""
    cls = _BACKENDS.get(settings.asset_storage_backend, LocalAssetStorage)
    return cls()
