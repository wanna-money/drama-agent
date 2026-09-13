"""作品级「小说改编 → 切成 N 段」服务。

产出是**每段一条 Story(原文片段)+ 一条 Script(该段的改编方案)**:
切分是原文层的关系(Story 自指 parent_id),改编是方案层的关系(Script.story_id)。
所以 LLM 要同时给出「这一段的原文」与「这一段的剧本」—— 只要剧本的话片段就没有原文,
用户改不动它,也无法只重炼这一段(那正是 1:1 时代的缺陷)。

不再有"草稿"这个中间态 —— 那会让同一份内容在 Project.adapted_draft 和落库处两处存在。

切分前取该作品已确认的角色名单作硬约束下发,各段人名因此一致,每段剧本继承同一份 cast:
没有约束时同一角色会在不同段被抽成不同称呼("李明"/"小李"/"李哥"),下游按 id 取造型
就会落空。由 JobKind.ADAPT 的 job 驱动(见 workflow/runner)。
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.config import settings
from drama_agent.db.enums import AdaptationStatus, Genre
from drama_agent.db.models import Project, Script
from drama_agent.services import episode_service, script_service, story_service
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.cast_constraint import cast_constraint_block
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

MAX_DRAFT_EPISODES = 100      # 防御:模型返回超长列表时截断

SYSTEM = system_prompt("""You are a professional screenwriter adapting long-form fiction
into a serialized short drama. Condense the source into per-episode screenplays that can be
shot directly.""")


def build_adaptation_prompt(
    source_text: str, target_episodes: int | None = None, seconds_per_ep: int | None = None,
    cast_names: list[str] | None = None,
) -> tuple[str, str]:
    """把小说改编成「分集剧本」的 prompt。切分模式二选一(接口层保证恰好一个非空):
    - target_episodes=N:要求恰好切 N 段
    - seconds_per_ep=S:告知每段成片约 S 秒的体量,段数由模型据故事长度自定

    cast_names:该作品已确认的角色名单,作为各段共用的硬约束(文案见 cast_constraint)。
    """
    if target_episodes:
        split_rule = f"把故事切成恰好 {target_episodes} 集,每集一段完整剧本。"
    else:
        split_rule = (f"按每集成片约 {seconds_per_ep} 秒的体量切分,"
                      "集数由你根据故事长度决定(不要为凑数拉长或压缩剧情)。")
    user_prompt = f"""把下面的故事改编成可直接拍摄的分集剧本。

SOURCE:
{source_text}
{cast_constraint_block(cast_names)}

切分要求:
- {split_rule}
- 每集自成起承转合,含场景、人物动作与对白。
- 保留主线、删枝节 —— 这是"精简后的改编稿",不是原文照搬。
- 同一个角色在各集里必须用**同一个名字**(跨集一致,不要换称呼)。

每集要给两份文本,各有其用,**不要互相替代**:
- `source`:这一集对应的**原文片段**(散文体,从 SOURCE 里节选/浓缩而来,不是剧本格式)。
  它是这一集的源头 —— 用户之后改它、只重新改编这一集时用的就是它。
- `screenplay`:由该片段改编出的**剧本**(场景标题 / 动作 / 对白)。

返回 JSON 数组,每集一项:
[
  {{"index": 1, "title": "第 1 集 · 标题",
    "source": "这一集对应的原文片段(散文体)",
    "screenplay": "完整剧本正文"}},
  ...
]"""
    return SYSTEM, user_prompt


def _coerce_draft(raw) -> list[dict]:
    """把模型产出规整成 [{index,title,source,screenplay}]。

    规范 6 的粒度:个别段畸形 → 丢弃 + warning;整份不是列表/全不可用 → 返回 []
    (调用方据此落 failed)。index 按保留顺序重排为连续 1..n。
    """
    if isinstance(raw, dict) and "episodes" in raw:
        raw = raw["episodes"]
    if not isinstance(raw, list):
        logger.warning("adaptation: draft is not a list", got=type(raw).__name__)
        return []
    out: list[dict] = []
    for pos, item in enumerate(raw[:MAX_DRAFT_EPISODES]):
        if not isinstance(item, dict):
            logger.warning("adaptation: drop non-dict draft item", position=pos)
            continue
        screenplay = str(item.get("screenplay") or "").strip()
        if not screenplay:
            logger.warning("adaptation: drop draft item without screenplay", position=pos)
            continue
        idx = len(out) + 1
        title = str(item.get("title") or "").strip() or f"第 {idx} 集"
        # source 缺失只记 warning、不丢弃该段:剧本本身可用,片段原文留空仍能开拍
        # (用户想改原文时再补)。丢掉整段的代价比原文留空大得多。
        source = str(item.get("source") or "").strip()
        if not source:
            logger.warning("adaptation: draft item has no source excerpt", position=pos)
        out.append({"index": idx, "title": title, "source": source,
                    "screenplay": screenplay})
    return out


async def analyze_cast(session: AsyncSession, project_id: str) -> dict:
    """切分**之前**先抽整本小说的角色,并对齐到作品角色库。

    为什么必须在切分前:切分后各段自行发明称呼,同一角色跨集就成了不同名字
    ("李默"/"小李"/"店员"),下游按 character_id 取造型必然落空。整本分析一次、
    人工确认一次,名单再作为硬约束下发给各段,身份才能跨集一致。

    有待确认项 → 落 cast_review 等人工;全部同名命中(或角色库读不到)→ 直接进 adapting。
    """
    from drama_agent.services import script_intake_service
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one()
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    resolved = await script_intake_service.analyze(
        project_id, project.source_text or "", dm.id if dm else None)
    project.cast_analysis = resolved["story_analysis"]
    project.cast_pending = resolved["pending"]
    project.adaptation_status = (
        AdaptationStatus.CAST_REVIEW.value if resolved["pending"]
        else AdaptationStatus.ADAPTING.value)
    await session.commit()
    return {
        "adaptation_status": project.adaptation_status,
        "pending": resolved["pending"],
        "cast": resolved["cast"],
    }


async def confirm_cast(
    session: AsyncSession, project_id: str, decisions: dict | None,
) -> dict | None:
    """人工确认角色身份 → 落成 Character 实体 → 进 adapting(交 job 继续切分)。

    仅 cast_review 可确认;其它状态返回 None(接口层转 409)。
    """
    from drama_agent.services import script_intake_service
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None or project.adaptation_status != AdaptationStatus.CAST_REVIEW.value:
        return None
    cast = await script_intake_service.apply_cast_only(
        project_id, project.cast_analysis, decisions)
    project.cast_pending = []
    project.adaptation_status = AdaptationStatus.ADAPTING.value
    await session.commit()
    return {"adaptation_status": project.adaptation_status, "cast": cast}


async def adapt(session: AsyncSession, project_id: str) -> dict:
    """跑切分:读作品配置 → 取已确认的角色名单 → LLM 切分 → 批量落成「片段 + 方案」。

    每段落两条记录:子 Story(原文片段,挂在作品的顶层 Story 下)+ Script(该段的方案)。
    角色在此之前已由 analyze_cast/confirm_cast 确立(见那两个函数的注释),故这里
    直接取角色库作名单。LLM 传输层异常**向上抛**(交 job 重试);产出不可用则落 failed。
    批量入库单事务:宁可一条不建,也不留半批(规范 6)。
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one()
    # 名单来自作品角色库:各段共用同一份约束与同一份 cast,跨集身份因此一致
    roster = await _roster_map(project_id)
    system, user = build_adaptation_prompt(
        project.source_text or "", project.target_episodes,
        project.target_seconds_per_episode, sorted(roster))
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    raw = await llm_service.complete_json(
        system, user, temperature=0.5, model=dm.id if dm else None)
    draft = _coerce_draft(raw)
    if not draft:
        project.adaptation_status = AdaptationStatus.FAILED.value
        await session.commit()
        logger.warning("adaptation: unusable draft, marked failed", project_id=project_id)
        return {"adaptation_status": project.adaptation_status, "scripts": []}

    created: list[dict] = []
    try:
        # 顶层 Story(整本小说)是各片段的父:切分关系走 Story 自指。
        # 没有它就无从表达"这些片段同属一本小说",片段会各自成为孤立原文。
        book = await _ensure_book_story(session, project)
        genre = project.genre or Genre.DRAMA.value
        for item in draft:
            seg = await story_service.create(
                session, title=item["title"], genre=genre, content=item["source"] or None,
                project_id=project_id, parent_id=book["id"], order_index=item["index"],
                # cast 落在片段原文上(权威在 Story);各段共用作品名单,跨集身份因此一致
                cast=roster or None, autocommit=False)
            created.append(await script_service.create(
                session, title=item["title"], genre=genre, story_id=seg["id"],
                project_id=project_id, content=item["screenplay"], autocommit=False))
        project.adaptation_status = AdaptationStatus.DONE.value
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return {"adaptation_status": AdaptationStatus.DONE.value, "scripts": created}


async def _ensure_book_story(session: AsyncSession, project: Project) -> dict:
    """该作品的顶层 Story(整本小说)。已有则复用 —— 重新改编不该再建一本。

    小说正文的权威正在从 Project.source_text 迁往 Story;此处以 Story 为准,
    没有则用 Project.source_text 建一条(迁移脚本之外的兜底,让新作品也走同一条路)。
    """
    tops = await story_service.list_stories(
        session, project_id=project.id, top_level_only=True)
    if tops:
        return tops[0]
    return await story_service.create(
        session, title=project.title, genre=project.genre or Genre.DRAMA.value,
        content=project.source_text, project_id=project.id,
        story_analysis=project.cast_analysis, autocommit=False)


async def _roster_map(project_id: str) -> dict[str, str]:
    """角色名 → Character.id。读不到时返回空(改编仍可完成,只是剧本没带 cast)。"""
    try:
        from drama_agent.services import character_entity_service as ce
        return {r.name: r.id for r in await ce.list_characters(project_id) if r.name}
    except Exception as e:  # noqa: BLE001 — 取不到就不带 cast,不阻断改编
        logger.warning("roster map lookup failed", error=str(e))
        return {}


async def commit(
    session: AsyncSession, project_id: str, *,
    llm_model: str, video_provider: str, resolution: str,
    video_model: str = "", use_keyframes: bool = False,
) -> list[dict] | None:
    """按该作品切出的方案批量建集(每集 = 一段片段原文 + 它的方案)。仅 done 态可提交。

    story_id 取自方案所属的片段原文 —— 那是集的锚点(分析/阵容/原文都从它取)。
    **不传 seed_screenplay**:runner._build_initial_state 里 screenplay_versions 优先于
    起始方案,两者同传会让方案正文被跳过。中途任一集失败则整体回滚,不留半个季(规范 6)。
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None or project.adaptation_status != AdaptationStatus.DONE.value:
        return None
    scripts = list((await session.execute(
        select(Script).where(Script.project_id == project_id)
        .order_by(Script.created_at.asc()))).scalars().all())
    if not scripts:
        return None
    target_seconds = project.target_seconds_per_episode or settings.target_episode_seconds
    created: list[dict] = []
    try:
        for sc in scripts:
            # 不传 episode_number:让 create 走 max+1 自动分配,绕开已占用的集号
            # (作品页的「新建一集」始终可见,用户先手建一集再来改编是常规操作)。
            if not sc.story_id:
                # 切分产出的方案必定带片段原文;没有则是未迁移的旧行,跳过而不是建一个
                # 跑不起来的集(它的第一步取不到任何输入)
                logger.warning("commit: skip script without story", script_id=sc.id)
                continue
            created.append(await episode_service.create(
                session, project_id=project_id, title=sc.title,
                story_id=sc.story_id, script_id=sc.id,
                llm_model=llm_model, video_provider=video_provider,
                video_model=video_model, resolution=resolution,
                target_seconds=target_seconds,
                use_keyframes=use_keyframes, autocommit=False))
        if not created:
            # 全部方案都没有原文归属(旧库)→ 回 None 让接口层报 409,
            # 而不是 commit 一个空事务再谎报成功
            await session.rollback()
            return None
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return created
