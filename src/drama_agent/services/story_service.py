"""stories 仓储:故事原文(内容的源头)的 CRUD。

Story 与 Script 是 1:N —— 一段原文可以有多个改编方案。切分则走 Story 的自指
parent_id(一本小说切出 N 片,每片是子 Story)。两种关系的语义见 models.Story。

原文正文、story_analysis、cast 的**唯一权威**在此;Script 只持成稿剧本正文。
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Story


def _to_dict(row: Story, project_title: str | None = None,
             script_count: int = 0, segment_count: int = 0) -> dict:
    """对外形状。计数由 _dict/_dicts 一次查好带上 —— 列表要显示"有几个方案/几段",
    让前端逐条再拉一次就是 N+1(而它也无从知道该拉哪个接口)。"""
    return {
        "id": row.id, "project_id": row.project_id, "parent_id": row.parent_id,
        "order_index": row.order_index,
        "title": row.title, "genre": row.genre, "content": row.content,
        "story_analysis": row.story_analysis, "cast": row.cast or {},
        "project_title": project_title,
        "script_count": script_count,      # 已有几个改编方案
        "segment_count": segment_count,    # 已切出几段(子 Story)
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _project_titles(session: AsyncSession, project_ids: set[str]) -> dict[str, str]:
    if not project_ids:
        return {}
    from drama_agent.db.models import Project
    rows = (await session.execute(
        select(Project.id, Project.title).where(Project.id.in_(project_ids)))).all()
    return {pid: title for pid, title in rows}


async def _counts(
    session: AsyncSession, story_ids: list[str]
) -> tuple[dict[str, int], dict[str, int]]:
    """(每个 story 的方案数, 每个 story 的片段数)。一次 group by,不做 N+1。"""
    from drama_agent.db.models import Script
    if not story_ids:
        return {}, {}
    scripts: dict[str, int] = {
        str(sid): int(n) for sid, n in (await session.execute(
            select(Script.story_id, func.count())
            .where(Script.story_id.in_(story_ids)).group_by(Script.story_id))).all()
        if sid
    }
    segs: dict[str, int] = {
        str(pid): int(n) for pid, n in (await session.execute(
            select(Story.parent_id, func.count())
            .where(Story.parent_id.in_(story_ids)).group_by(Story.parent_id))).all()
        if pid
    }
    return scripts, segs


async def _dicts(session: AsyncSession, rows: list[Story]) -> list[dict]:
    titles = await _project_titles(session, {r.project_id for r in rows if r.project_id})
    scripts, segs = await _counts(session, [r.id for r in rows])
    return [
        _to_dict(r, titles.get(r.project_id) if r.project_id else None,
                 scripts.get(r.id, 0), segs.get(r.id, 0))
        for r in rows
    ]


async def _dict(session: AsyncSession, row: Story) -> dict:
    return (await _dicts(session, [row]))[0]


async def create(
    session: AsyncSession, *, title: str, genre: str = "drama",
    content: str | None = None, project_id: str | None = None,
    parent_id: str | None = None, order_index: int = 0,
    story_analysis: dict | None = None, cast: dict | None = None,
    autocommit: bool = True,
) -> dict:
    """建一条原文。autocommit=False 只 flush,由调用方统一 commit
    (小说切分批量入库要"全成或全不成",半批片段比没有更糟)。"""
    row = Story(
        id=str(uuid.uuid4()), title=title, genre=genre, content=content,
        project_id=project_id, parent_id=parent_id, order_index=order_index,
        story_analysis=story_analysis, cast=cast or None,
    )
    session.add(row)
    if autocommit:
        await session.commit()
        await session.refresh(row)
    else:
        await session.flush()
    return await _dict(session, row)


async def get(session: AsyncSession, story_id: str) -> dict | None:
    row = (await session.execute(
        select(Story).where(Story.id == story_id))).scalar_one_or_none()
    return await _dict(session, row) if row else None


async def row_of(session: AsyncSession, story_id: str) -> Story | None:
    """拿 ORM 行(内部用:需要读 content/cast 原值而不是对外形状时)。"""
    return (await session.execute(
        select(Story).where(Story.id == story_id))).scalar_one_or_none()


async def list_stories(
    session: AsyncSession, *, project_id: str | None = None,
    parent_id: str | None = None, top_level_only: bool = False,
) -> list[dict]:
    """原文列表。

    top_level_only:只列顶层原文(parent_id IS NULL)—— 故事库总览要的是"有哪些故事",
    切出来的片段属于其父原文的内部结构,平铺在总览里会把一本小说的 20 段和别的故事混在
    一起,用户分不出哪些是一组。
    """
    q = select(Story)
    if project_id is not None:
        q = q.where(Story.project_id == project_id)
    if parent_id is not None:
        q = q.where(Story.parent_id == parent_id)
    elif top_level_only:
        q = q.where(Story.parent_id.is_(None))
    # 片段按剧情次序,顶层按新→旧。切分是并发入库的,创建时间与剧情顺序无关。
    q = q.order_by(Story.order_index.asc(), Story.created_at.desc())
    rows = list((await session.execute(q)).scalars().all())
    return await _dicts(session, rows)


async def update(
    session: AsyncSession, story_id: str, *,
    title: str | None = None, content: str | None = None,
    story_analysis: dict | None = None, cast: dict | None = None,
    project_id: str | None = None, unset_project: bool = False,
) -> dict | None:
    """改原文(只改传了的字段)。

    改原文**不会**自动更新已有的改编方案:那些剧本是独立的产出,要重新改编才会跟上。
    界面须说清这一点 —— 否则用户以为改了原文剧本就同步了。
    """
    row = await row_of(session, story_id)
    if row is None:
        return None
    if title is not None:
        row.title = title
    if content is not None:
        row.content = content
    if story_analysis is not None:
        row.story_analysis = story_analysis
    if cast is not None:
        row.cast = cast or None
    # 归属可改(移到别的作品 / 解绑成散稿)。unset_project 与 project_id 分开表达 ——
    # 只用 None 无法区分"不改归属"和"改成散稿"。
    if unset_project:
        row.project_id = None
    elif project_id is not None:
        row.project_id = project_id
    await session.commit()
    await session.refresh(row)
    return await _dict(session, row)


async def referencing_scripts(session: AsyncSession, story_ids: list[str]) -> int:
    """有多少改编方案挂在这些原文下(含其子片段下的)。

    删原文前必须查:剧本的 story_id 指向它,删掉原文会让那些剧本再也取不到原文
    (提炼 prompt、重新改编都要读它)。
    """
    from drama_agent.db.models import Script
    if not story_ids:
        return 0
    ids = set(story_ids) | {s["id"] for s in await _descendants(session, story_ids)}
    return int((await session.execute(
        select(func.count()).select_from(Script)
        .where(Script.story_id.in_(ids)))).scalar() or 0)


async def _descendants(session: AsyncSession, story_ids: list[str]) -> list[dict]:
    """所有后代片段(逐层查,不用递归 CTE —— SQLite 与 PG 的写法有差异,
    而切分只有一层深,逐层查的代价可忽略)。"""
    out: list[dict] = []
    frontier = list(story_ids)
    seen: set[str] = set(frontier)
    while frontier:
        rows = list((await session.execute(
            select(Story).where(Story.parent_id.in_(frontier)))).scalars().all())
        frontier = [r.id for r in rows if r.id not in seen]
        seen.update(frontier)
        out.extend({"id": r.id} for r in rows)
    return out


async def delete(session: AsyncSession, story_id: str) -> bool:
    """删一条原文,连同它切出的片段(片段是它的内部结构,留下就是悬空)。

    调用方须先用 referencing_scripts 挡住"还有改编方案在用"的情况。
    """
    row = await row_of(session, story_id)
    if row is None:
        return False
    for d in await _descendants(session, [story_id]):
        child = await row_of(session, d["id"])
        if child is not None:
            await session.delete(child)
    await session.delete(row)
    await session.commit()
    return True
