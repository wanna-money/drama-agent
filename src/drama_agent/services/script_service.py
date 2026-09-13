"""scripts 仓储:剧本(一段原文的一个改编方案)的 CRUD。

原文正文 / story_analysis / cast 的权威在 Story(见 story_service)—— 本模块**不写**
Script 上那三个旧列。剧本要用它们时经 story_id 取,故对外形状里带上 story_* 字段
(由后端一次查好,前端不用再拉一次原文)。

版本树/审核/生成状态在 Episode(见 episode_service)。
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Script, Story


def _to_dict(row: Script, project_title: str | None = None,
             story: Story | None = None) -> dict:
    """对外形状。**project_title / story_* 是这里的一部分**,不是列表接口的额外装饰 ——
    单条与列表若各自决定带不带,前端在详情页就会拿到 undefined 而把有归属的剧本显示成
    「未归属」(实测过的症状)。新增出口一律走 _dict / _dicts。

    source_text 仍下发,值取自 **Story.content**(不是 Script 上那个旧列):
    下游(提炼 prompt、剧集页故事卡)按这个名字消费原文,换名要动一圈调用方,
    而它的语义没变 —— 变的只是权威存在哪。
    """
    return {
        "id": row.id, "project_id": row.project_id,
        "story_id": row.story_id,
        "title": row.title, "genre": row.genre,
        "content": row.content,
        # 原文侧(权威在 Story)
        "source_text": (story.content if story else None),
        "story_analysis": (story.story_analysis if story else None),
        "cast": (story.cast or {}) if story else {},
        "story_title": (story.title if story else None),
        "project_title": project_title,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _stories(session: AsyncSession, story_ids: set[str]) -> dict:
    if not story_ids:
        return {}
    rows = (await session.execute(
        select(Story).where(Story.id.in_(story_ids)))).scalars().all()
    return {r.id: r for r in rows}


async def _dicts(session: AsyncSession, rows: list[Script]) -> list[dict]:
    """多条 + 一次查全部作品名与原文(不做 N+1)。"""
    titles = await _project_titles(session, {r.project_id for r in rows if r.project_id})
    stories = await _stories(session, {r.story_id for r in rows if r.story_id})
    return [
        _to_dict(r, titles.get(r.project_id) if r.project_id else None,
                 stories.get(r.story_id) if r.story_id else None)
        for r in rows
    ]


async def _dict(session: AsyncSession, row: Script) -> dict:
    return (await _dicts(session, [row]))[0]


async def story_of(session: AsyncSession, script: Script | None) -> Story | None:
    """某剧本改编自的那段原文(ORM 行)。

    读原文正文 / story_analysis / cast 的**唯一入口**:那三样的权威在 Story,而 Script
    上的同名列已停写(只余旧数据)。直接读 `sc.source_text` 之类会在迁移后静默拿到 NULL
    —— 不抛异常,只是原文变空串、角色清单变空,故一律经此取。
    """
    if script is None or not script.story_id:
        return None
    return (await session.execute(
        select(Story).where(Story.id == script.story_id))).scalar_one_or_none()


async def create(
    session: AsyncSession, *, title: str, story_id: str, genre: str = "drama",
    project_id: str | None = None, content: str | None = None,
    autocommit: bool = True,
) -> dict:
    """建一个改编方案。story_id 必填 —— 剧本总是某段原文的方案,没有孤立的剧本
    (那正是 1:1 时代把原文塞进 Script 造成的混乱)。

    autocommit=False 只 flush,由调用方统一 commit(批量入库要"全成或全不成")。
    """
    row = Script(
        id=str(uuid.uuid4()), title=title, genre=genre, story_id=story_id,
        project_id=project_id, content=content,
    )
    session.add(row)
    if autocommit:
        await session.commit()
        await session.refresh(row)
    else:
        await session.flush()
    return await _dict(session, row)


async def create_from_episode(session: AsyncSession, episode_id: str) -> dict | None:
    """把某集已通过的剧本另存为复用素材:挂在**该集拍的那段原文**下,成为它的又一个方案。

    这正是 1:N 的用处 —— 从一段原文开拍、改出了满意的剧本,存下来时不必再复制一份原文;
    它与原有方案并列,下次可直接对比取用。原文经 ep.story_id 直取(集的锚点),
    不绕起始方案:从故事开跑的集没有起始方案,绕过去就存不了。
    """
    from drama_agent.db.models import Episode
    ep = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if ep is None:
        return None
    snap = ep.state_snapshot or {}
    screenplay = snap.get("screenplay") or ""
    if not screenplay.strip():
        return None
    if not ep.story_id:
        return None       # 未迁移的旧集没有原文锚点:不猜一个
    analysis = snap.get("story_analysis")
    genre = (analysis or {}).get("genre") if isinstance(analysis, dict) else None
    # 该集确认的阵容回写原文侧(权威在 Story):下次用同一段原文开拍即可继承,
    # 不必重新确认;写进 Script 则每个方案各持一份并逐渐漂移。
    if snap.get("cast"):
        from drama_agent.services import story_service
        await story_service.update(session, ep.story_id, cast=snap["cast"])
    return await create(
        session, title=ep.title, genre=genre or "drama",
        story_id=ep.story_id, content=screenplay, project_id=ep.project_id,
    )


async def list_scripts(
    session: AsyncSession, project_id: str | None = None, story_id: str | None = None,
) -> list[dict]:
    """剧本列表。project_id / story_id 传了才过滤;都不传返回全部。

    每条附 project_title 与原文侧字段(散稿/无原文为 None)—— 关联数据由后端一次查好,
    前端不用再拉一遍项目或原文列表自己拼。
    """
    q = select(Script).order_by(Script.created_at.desc())
    if project_id is not None:
        q = q.where(Script.project_id == project_id)
    if story_id is not None:
        q = q.where(Script.story_id == story_id)
    rows = list((await session.execute(q)).scalars().all())
    return await _dicts(session, rows)


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
    return await _dict(session, row) if row else None


async def update(
    session: AsyncSession, script_id: str, *,
    title: str | None = None, content: str | None = None,
    project_id: str | None = None, unset_project: bool = False,
) -> dict | None:
    """改剧本(只改传了的字段)。此处只改**剧本正文** ——
    原文 / story_analysis / cast 要改去 story_service(权威在那)。

    已建集的剧本仍可改:Episode 建集时把正文快照进自己的版本树,改剧本不影响在制作中
    的集(那些集的内容以其版本树为准)。
    """
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return None
    if title is not None:
        row.title = title
    if content is not None:
        row.content = content
    # 归属可改(移到别的作品 / 解绑成散稿)。unset_project 与 project_id 分开表达 ——
    # 只用 None 无法区分"不改归属"和"改成散稿"。
    if unset_project:
        row.project_id = None
    elif project_id is not None:
        row.project_id = project_id
    await session.commit()
    await session.refresh(row)
    return await _dict(session, row)


async def referencing_episodes(session: AsyncSession, script_ids: list[str]) -> int:
    """有多少集引用了这些剧本。集的 script_id 必填,删掉被引用的剧本会让那些集
    再也算不出入口模式、跑不起来 —— 故删除前必须查这个数。"""
    from drama_agent.db.models import Episode
    if not script_ids:
        return 0
    return int((await session.execute(
        select(func.count()).select_from(Episode)
        .where(Episode.script_id.in_(script_ids)))).scalar() or 0)


async def delete(session: AsyncSession, script_id: str) -> bool:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def delete_many(session: AsyncSession, script_ids: list[str]) -> int:
    """整组删除(如一本小说切出的全部分集)。返回真正删掉的条数。

    调用方须先用 referencing_episodes 挡住"还有集在用"的情况:此处不做守卫,
    是因为守卫要回 409 与具体数字,属接口层职责。
    """
    if not script_ids:
        return 0
    rows = list((await session.execute(
        select(Script).where(Script.id.in_(script_ids)))).scalars().all())
    for r in rows:
        await session.delete(r)
    await session.commit()
    return len(rows)
