"""项目级角色实体:Character / Look(造型)/ 三视图 CRUD。

与 character_service.py(DramaState 角色外貌描述存取)不同,后者不动。
session 动态查 db_session.AsyncSessionLocal;三视图文件委派 AssetStorage 工厂。
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select

from drama_agent.db.enums import CharacterView
from drama_agent.services.asset_storage import get_asset_storage

if TYPE_CHECKING:  # 仅类型检查期可见,运行时仍走函数内惰性 import
    from drama_agent.db.models import Character

_VIEW_KEY = {
    CharacterView.FRONT.value: "front_key",
    CharacterView.SIDE.value: "side_key",
    CharacterView.BACK.value: "back_key",
    CharacterView.FACE.value: "face_key",
}


async def create_character(project_id: str, name: str, description: str | None = None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        row = Character(id=str(uuid.uuid4()), project_id=project_id, name=name,
                        description=description)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def list_characters(project_id: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        return list((await s.execute(
            select(Character).where(Character.project_id == project_id)
        )).scalars().all())


async def get_character_by_name(project_id: str, name: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        return (await s.execute(
            select(Character).where(Character.project_id == project_id, Character.name == name)
        )).scalar_one_or_none()


async def get_character(character_id: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        return (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()


async def get_look(look_id: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    async with db_session.AsyncSessionLocal() as s:
        return (await s.execute(
            select(Look).where(Look.id == look_id))).scalar_one_or_none()


async def update_character(character_id: str, *, name: str | None = None,
                           description: str | None = None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        await s.commit()
        await s.refresh(row)
        return row


async def list_looks(character_id: str):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    async with db_session.AsyncSessionLocal() as s:
        return list((await s.execute(
            select(Look).where(Look.character_id == character_id))).scalars().all())


async def create_look(character_id: str, name: str = "默认造型", is_default: bool = False):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    async with db_session.AsyncSessionLocal() as s:
        existing = list((await s.execute(
            select(Look).where(Look.character_id == character_id))).scalars().all())
        force_default = is_default or len(existing) == 0
        if force_default:
            for lk in existing:
                lk.is_default = False
        row = Look(id=str(uuid.uuid4()), character_id=character_id, name=name,
                   is_default=force_default)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def update_look(look_id: str, *, name: str | None = None, is_default: bool | None = None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Look).where(Look.id == look_id))).scalar_one_or_none()
        if row is None:
            return None
        if name is not None:
            row.name = name
        if is_default is True:
            for lk in (await s.execute(select(Look).where(
                    Look.character_id == row.character_id))).scalars().all():
                lk.is_default = (lk.id == look_id)
        await s.commit()
        await s.refresh(row)
        return row


async def set_view(look_id: str, view: str, content: bytes, filename: str, mime: str | None):
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    field = _VIEW_KEY[view]  # KeyError 由调用方(API)先校验 view
    storage = get_asset_storage()
    key = await storage.save(content, filename)
    old = None
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Look).where(Look.id == look_id))).scalar_one_or_none()
        if row is None:
            await storage.delete(key)
            return None
        old = getattr(row, field)
        setattr(row, field, key)
        await s.commit()
        await s.refresh(row)
    if old:
        try:
            await storage.delete(old)
        except Exception:  # noqa: BLE001 — 旧文件删除失败不阻断
            pass
    return row


async def read_view_bytes(look_id: str, view: str) -> bytes | None:
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    field = _VIEW_KEY[view]
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Look).where(Look.id == look_id))).scalar_one_or_none()
    if row is None or getattr(row, field) is None:
        return None
    return await get_asset_storage().read(getattr(row, field))


async def delete_look(look_id: str) -> bool:
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Look
    storage = get_asset_storage()
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Look).where(Look.id == look_id))).scalar_one_or_none()
        if row is None:
            return False
        keys = [row.front_key, row.side_key, row.back_key, row.face_key]
        await s.delete(row)
        await s.commit()
    for k in keys:
        if k:
            try:
                await storage.delete(k)
            except Exception:  # noqa: BLE001
                pass
    return True


async def set_voice(character_id: str, content: bytes, filename: str,
                    mime: str | None) -> "Character | None":
    """绑定/换绑角色音色样本。换绑时删旧文件(失败不阻断);角色不存在 → None。"""
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    storage = get_asset_storage()
    key = await storage.save(content, filename)
    old = None
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
        if row is None:
            await storage.delete(key)
            return None
        old = row.voice_key
        row.voice_key = key
        await s.commit()
        await s.refresh(row)
    if old:
        try:
            await storage.delete(old)
        except Exception:  # noqa: BLE001 — 旧文件删除失败不阻断
            pass
    return row


async def read_voice_bytes(character_id: str) -> bytes | None:
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
    if row is None or row.voice_key is None:
        return None
    return await get_asset_storage().read(row.voice_key)


async def clear_voice(character_id: str) -> "Character | None":
    """解绑音色(幂等:未绑定时也返回该行)。角色不存在 → None。"""
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character
    old = None
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
        if row is None:
            return None
        old = row.voice_key
        row.voice_key = None
        await s.commit()
        await s.refresh(row)
    if old:
        try:
            await get_asset_storage().delete(old)
        except Exception:  # noqa: BLE001 — 文件删除失败不阻断
            pass
    return row


async def delete_character(character_id: str) -> bool:
    from drama_agent.db import session as db_session
    from drama_agent.db.models import Character, Look
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
        if row is None:
            return False
        look_ids = [x.id for x in (await s.execute(
            select(Look).where(Look.character_id == character_id))).scalars().all()]
    for lid in look_ids:
        await delete_look(lid)   # 复用:删文件 + 删行
    async with db_session.AsyncSessionLocal() as s:
        row = (await s.execute(
            select(Character).where(Character.id == character_id))).scalar_one_or_none()
        if row:
            await s.delete(row)
            await s.commit()
    return True
