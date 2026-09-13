"""内容入库:分析文本 → 角色对齐 → 落成 Story(+ 可选的首个 Script)。

原文与剧本是 1:N:入库先建 **Story**(原文,持 story_analysis 与 cast),再按需给它建
一个 Script(改编方案)。从一段故事新建时通常只有原文、还没有方案 —— 方案由制作流程的
screenplay_writer 产出或用户后续添加。

为什么对齐放在入库、不放在建集:同一段原文可能被多集引用,放在建集就要确认多遍、
还可能选得不一致。入库时对齐一次,建集直接继承 —— 角色名单是原文的属性。

与制作流程里的 cast_review(LangGraph interrupt)不同:那个绑定 Episode 的 thread、
需要 checkpointer;剧本入库不在图里跑,用普通请求-响应(analyze → 用户确认 → create)
即可,不引入图状态。
"""
from __future__ import annotations

import structlog

from drama_agent.db.enums import Genre
from drama_agent.services import cast_service

logger = structlog.get_logger()


async def apply_cast_only(
    project_id: str, story_analysis: dict | None, cast_decisions: dict | None,
) -> dict[str, str]:
    """只落角色身份、不建剧本。供小说改编用:切分前先把整本的角色确立下来,
    切分时才有名单可约束(否则各段自行发明称呼,同一角色跨集就漂移了)。"""
    return await cast_service.apply_decisions(project_id, story_analysis, cast_decisions)


async def analyze(
    project_id: str | None, source_text: str, llm_model: str | None = None
) -> dict:
    """分析一段文本并对齐到作品角色库。

    返回 {story_analysis, cast, pending}:
      cast    —— 已能确定身份的(与已有角色同名)
      pending —— 需人工确认的(名单外的新名字),为空即无需确认
    复用 story_analyzer 的 prompt 构造与 cast_service 的对齐逻辑,不另写一份
    (同一件事两处实现迟早分叉)。
    """
    from drama_agent.services.llm_service import llm_service
    from drama_agent.workflow.nodes.story_analyzer import _known_characters, build_prompt

    # 无作品(散稿)时没有角色库可对齐 —— 分析照做,但不产出待确认项
    known = await _known_characters(project_id) if project_id else []
    # 分析节点的 prompt 把 genre 当"要回显的枚举",写死 DRAMA 就会回显 drama,
    # 而那个回显值在 runner 的链里**排在最前**(它被当作分析结论)——
    # 于是用户建作品时选的类型被一个凭空的默认值压过,且没有任何报错。
    genre = Genre.DRAMA.value
    if project_id:
        from drama_agent.db import session as db_session
        async with db_session.AsyncSessionLocal() as s:
            genre = await _project_genre(s, project_id) or genre
    system, user = build_prompt(source_text, genre, known)
    analysis = await llm_service.complete_json(
        system, user, temperature=0.3, model=llm_model)
    if not project_id:
        return {"story_analysis": analysis, "cast": {}, "pending": []}
    resolved = await cast_service.resolve(project_id, analysis)
    return {
        "story_analysis": analysis,
        "cast": resolved["cast"],
        "pending": resolved["pending"],
    }


async def _project_genre(session, project_id: str) -> str | None:
    """归属作品的类型;取不到返回 None(调用方继续往下兜)。

    查不到不抛:作品可能已删(散稿原文仍可建),那不该阻断建原文。
    """
    from sqlalchemy import select

    from drama_agent.db.models import Project

    row = (await session.execute(
        select(Project.genre).where(Project.id == project_id))).scalar_one_or_none()
    return row or None


async def create_with_cast(
    session, *, project_id: str | None, title: str, source_text: str,
    story_analysis: dict | None = None, genre: str | None = None,
    cast_decisions: dict | None = None,
    content: str | None = None, autocommit: bool = True,
    parent_story_id: str | None = None, order_index: int = 0,
) -> dict:
    """落一条原文(Story),并把人工确认结果落成 cast(需要新建的角色在此建实体)。

    content 非空时顺带建一个 Script(该原文的首个改编方案)—— 小说切分走这条:
    切出的每段既有原文片段(content 参数外的 source_text)又有成稿剧本。
    只有原文时不建 Script:方案由制作流程产出,提前建一个空方案是凭空的记录。

    parent_story_id:这段原文是某段更长原文切出来的(切分关系走 Story 自指)。

    genre 优先取显式传入(用户在界面上选的类型);缺省才退到 story_analysis 的回显值,
    两者都没有才落 drama —— 分析节点只回显收到的值,不是类型的权威来源。

    返回 Story 的对外形状,额外带 `script_id`(刚建的方案;没建则为 None)——
    调用方(建集/前端跳转)需要它,让它们再查一次是 N+1 且它们无从知道查哪条。

    cast_decisions 是 analyze 返回的 pending 经用户确认后的决策
    ({名字: {action: link|create, character_id?}});未给决策的名字按新建处理
    (走到这一步说明它在文本里出场,丢掉会让下游取不到它的角色图)。
    """
    from drama_agent.services import script_service, story_service

    # 散稿没有作品级角色库,不落角色实体(建集时归属确定后再对齐)
    cast = (await cast_service.apply_decisions(project_id, story_analysis, cast_decisions)
            if project_id else {})
    # 归属作品的类型是**用户唯一显式选过**的那个值(建作品时选的;建集表单上没有
    # 类型选择器)。在此继承而非要求每个调用方都记得传 —— 漏传的调用方会静默落
    # drama,而界面上完全看不出:一个仙侠本子被当现代剧分镜。
    if not genre and project_id:
        genre = await _project_genre(session, project_id)
    genre = genre or (story_analysis or {}).get("genre") or Genre.DRAMA.value
    story = await story_service.create(
        session, title=title, genre=genre, content=source_text,
        project_id=project_id, parent_id=parent_story_id, order_index=order_index,
        story_analysis=story_analysis, cast=cast, autocommit=autocommit,
    )
    script_id = None
    if (content or "").strip():
        script = await script_service.create(
            session, title=title, genre=genre, story_id=story["id"],
            project_id=project_id, content=content, autocommit=autocommit,
        )
        script_id = script["id"]
    return {**story, "script_id": script_id}
