"""素材库服务:元数据 CRUD(assets 表)+ 文件委派 AssetStorage 工厂。

session 动态查 db_session.AsyncSessionLocal(可测试重绑)。
"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from drama_agent.services.asset_storage import get_asset_storage


async def create_asset(category: str, name: str, description: str | None,
                       content: bytes, filename: str, mime: str | None = None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Asset
    storage = get_asset_storage()
    key = await storage.save(content, filename)
    async with db_session.AsyncSessionLocal() as s:
        row = Asset(
            id=str(uuid.uuid4()), category=category, name=name, description=description,
            storage_key=key, mime=mime, size_bytes=len(content),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def list_assets(category: str | None = None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Asset
    async with db_session.AsyncSessionLocal() as s:
        stmt = select(Asset)
        if category:
            stmt = stmt.where(Asset.category == category)
        return list((await s.execute(stmt)).scalars().all())


async def get_asset(asset_id: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Asset
    async with db_session.AsyncSessionLocal() as s:
        return (await s.execute(
            select(Asset).where(Asset.id == asset_id)
        )).scalar_one_or_none()


async def update_asset(asset_id: str, *, name: str | None = None, description: str | None = None,
                       content: bytes | None = None, filename: str | None = None,
                       mime: str | None = None):
    """改名称/描述,可选换图(换图则存新文件、删旧文件)。返回更新后的行或 None。"""
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Asset
    storage = get_asset_storage()
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Asset).where(Asset.id == asset_id))).scalar_one_or_none()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        old_key = None
        if content is not None:
            old_key = row.storage_key
            row.storage_key = await storage.save(content, filename or "upload.png")
            row.size_bytes = len(content)
            if mime is not None:
                row.mime = mime
        await s.commit()
        await s.refresh(row)
    if old_key:
        try:
            await storage.delete(old_key)
        except Exception:  # noqa: BLE001 — 旧文件删除失败不阻断(孤儿文件无害)
            pass
    return row


async def delete_asset(asset_id: str) -> bool:
    """先删行(真相),后尽力删文件。返回是否存在并删除。"""
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Asset
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(select(Asset).where(Asset.id == asset_id))).scalar_one_or_none()
        if row is None:
            return False
        key = row.storage_key
        await s.delete(row)
        await s.commit()
    try:
        await get_asset_storage().delete(key)
    except Exception:  # noqa: BLE001
        pass
    return True


async def read_asset_bytes(asset_id: str) -> bytes | None:
    """读素材文件字节(供「拷贝进剧集参考」)。asset 不存在返回 None。"""
    row = await get_asset(asset_id)
    if row is None:
        return None
    return await get_asset_storage().read(row.storage_key)
