"""角色外貌(运行时项目数据)存取:PG 表 character_profiles。

原先误存于向量库(按主键精确取、从不语义检索),迁到结构化 PG 表。
"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.models import CharacterProfile


async def save(session: AsyncSession, project_id: str, name: str, appearance: str) -> None:
    """按 (project_id, name) upsert 角色外貌。"""
    row = (await session.execute(
        select(CharacterProfile).where(
            CharacterProfile.project_id == project_id, CharacterProfile.name == name)
    )).scalar_one_or_none()
    if row is not None:
        row.appearance = appearance
    else:
        session.add(CharacterProfile(
            id=str(uuid.uuid4()), project_id=project_id, name=name, appearance=appearance))
    await session.commit()


async def get(session: AsyncSession, project_id: str, name: str) -> str | None:
    row = (await session.execute(
        select(CharacterProfile).where(
            CharacterProfile.project_id == project_id, CharacterProfile.name == name)
    )).scalar_one_or_none()
    return row.appearance if row else None
