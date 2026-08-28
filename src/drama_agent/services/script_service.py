"""scripts 仓储:剧本库(只读复用素材)的 CRUD + 从剧集存入。

剧本库不再有 graph run —— Script 只由「某集剧本通过后存入」产生(create_from_episode),
或历史散稿。版本树/审核/生成状态全部搬到 Episode(见 episode_service)。
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Script


def _to_dict(row: Script) -> dict:
    return {
        "id": row.id, "project_id": row.project_id,
        "title": row.title, "genre": row.genre, "source_text": row.source_text,
        "story_analysis": row.story_analysis, "content": row.content,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create(
    session: AsyncSession, *, title: str, genre: str = "drama",
    source_text: str | None = None, project_id: str | None = None,
    story_analysis: dict | None = None, content: str | None = None,
) -> dict:
    row = Script(
        id=str(uuid.uuid4()), title=title, genre=genre, source_text=source_text,
        project_id=project_id, story_analysis=story_analysis, content=content,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def create_from_episode(session: AsyncSession, episode_id: str) -> dict | None:
    """把某集已通过的剧本另存为复用素材(剧本库)。正文取自该集图状态快照。"""
    from drama_agent.db.models import Episode
    ep = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if ep is None:
        return None
    snap = ep.state_snapshot or {}
    screenplay = snap.get("screenplay") or ""
    if not screenplay.strip():
        return None
    analysis = snap.get("story_analysis")
    genre = (analysis or {}).get("genre") if isinstance(analysis, dict) else None
    return await create(
        session, title=ep.title, genre=genre or "drama",
        source_text=ep.raw_input, story_analysis=analysis, content=screenplay,
        project_id=ep.project_id,
    )


async def list_scripts(session: AsyncSession, project_id: str | None = None) -> list[dict]:
    """剧本列表。project_id 传了才按作品过滤;不传返回全部(含散稿)。

    每条附 project_title(散稿为 None)供前端标注归属 —— 关联标题由后端一次查好,
    前端不用再拉一遍项目列表自己拼。
    """
    q = select(Script).order_by(Script.created_at.desc())
    if project_id is not None:
        q = q.where(Script.project_id == project_id)
    rows = list((await session.execute(q)).scalars().all())
    titles = await _project_titles(session, {r.project_id for r in rows if r.project_id})
    return [
        {**_to_dict(r), "project_title": titles.get(r.project_id) if r.project_id else None}
        for r in rows
    ]


async def _project_titles(session: AsyncSession, project_ids: set[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    from drama_agent.db.models import Project
    rows = (await session.execute(
        select(Project.id, Project.title).where(Project.id.in_(project_ids)))).all()
    return {pid: title for pid, title in rows}


async def get(session: AsyncSession, script_id: str) -> dict | None:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    return _to_dict(row) if row else None


async def delete(session: AsyncSession, script_id: str) -> bool:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
