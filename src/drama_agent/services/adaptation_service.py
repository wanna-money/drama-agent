"""作品级「小说改编 → 分集切分」服务。

改编产出是"分集剧本"级(每段可直接进分镜),由 JobKind.ADAPT 的 job 驱动(见 workflow/runner)。
设计见 docs/superpowers/specs/2026-08-25-novel-adaptation-episode-split-design.md
"""
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.config import settings
from drama_agent.db.enums import AdaptationStatus
from drama_agent.db.models import Project
from drama_agent.services import episode_service
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

MAX_DRAFT_EPISODES = 100      # 防御:模型返回超长列表时截断

SYSTEM = system_prompt("""You are a professional screenwriter adapting long-form fiction
into a serialized short drama. Condense the source into per-episode screenplays that can be
shot directly.""")


def build_adaptation_prompt(
    source_text: str, target_episodes: int | None = None, seconds_per_ep: int | None = None,
) -> tuple[str, str]:
    """把小说改编成「分集剧本」的 prompt。切分模式二选一(接口层保证恰好一个非空):
    - target_episodes=N:要求恰好切 N 段
    - seconds_per_ep=S:告知每段成片约 S 秒的体量,段数由模型据故事长度自定
    """
    if target_episodes:
        split_rule = f"把故事切成恰好 {target_episodes} 集,每集一段完整剧本。"
    else:
        split_rule = (f"按每集成片约 {seconds_per_ep} 秒的体量切分,"
                      "集数由你根据故事长度决定(不要为凑数拉长或压缩剧情)。")
    user_prompt = f"""把下面的故事改编成可直接拍摄的分集剧本。

SOURCE:
{source_text}

切分要求:
- {split_rule}
- 每集自成起承转合,含场景、人物动作与对白。
- 保留主线、删枝节 —— 这是"精简后的改编稿",不是原文照搬。

返回 JSON 数组,每集一项:
[
  {{"index": 1, "title": "第 1 集 · 标题", "screenplay": "完整剧本正文"}},
  ...
]"""
    return SYSTEM, user_prompt


def _coerce_draft(raw) -> list[dict]:
    """把模型产出规整成 [{index,title,screenplay}]。

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
        out.append({"index": idx, "title": title, "screenplay": screenplay})
    return out


async def adapt(session: AsyncSession, project_id: str) -> dict:
    """跑改编:读作品配置 → LLM → 规整 → 写 adapted_draft + adaptation_status。

    LLM 传输层异常**向上抛**(交 job 重试);产出不可用则落 failed(重试无意义)。
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one()
    system, user = build_adaptation_prompt(
        project.source_text or "", project.target_episodes,
        project.target_seconds_per_episode)
    from drama_agent import provider as provider_pkg
    dm = provider_pkg.provider_registry.effective_default("llm")
    raw = await llm_service.complete_json(
        system, user, temperature=0.5, model=dm.id if dm else None)
    draft = _coerce_draft(raw)
    if not draft:
        project.adaptation_status = AdaptationStatus.FAILED.value
        await session.commit()
        logger.warning("adaptation: unusable draft, marked failed", project_id=project_id)
        return {"adaptation_status": project.adaptation_status, "adapted_draft": []}
    project.adapted_draft = draft
    project.adaptation_status = AdaptationStatus.DRAFT_READY.value
    await session.commit()
    return {"adaptation_status": project.adaptation_status, "adapted_draft": draft}


async def save_draft(session: AsyncSession, project_id: str, draft: list[dict]) -> dict | None:
    """存人工编辑后的草稿(整表覆盖 = 幂等)。仅 draft_ready 可写;
    状态不允许返回 None(接口层转 409)。草稿非空由接口层校验(空 → 422)。"""
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None or project.adaptation_status != AdaptationStatus.DRAFT_READY.value:
        return None
    project.adapted_draft = _coerce_draft(draft)
    await session.commit()
    return {"adaptation_status": project.adaptation_status, "adapted_draft": project.adapted_draft}


async def commit(
    session: AsyncSession, project_id: str, *,
    llm_model: str, video_provider: str, resolution: str,
    video_model: str = "", use_keyframes: bool = False,
) -> list[dict] | None:
    """据 adapted_draft 单事务批量建 N 集,置 committed。

    仅 draft_ready 可提交(其它状态返回 None → 接口 409)。中途任一集创建失败则
    整体回滚:宁可一集不建,也不留半个季(规范 6)。
    """
    project = (await session.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None or project.adaptation_status != AdaptationStatus.DRAFT_READY.value:
        return None
    draft = project.adapted_draft or []
    target_seconds = project.target_seconds_per_episode or settings.target_episode_seconds
    created: list[dict] = []
    try:
        for item in draft:
            # 不传 episode_number:让 create 走既有的 max+1 自动分配,绕开已占用的集号。
            # 用草稿 index 硬指定会撞 uq_episode_number —— 作品页的「新建一集」始终可见,
            # 用户先手建一集再来改编是常规操作。草稿顺序仍对应最终集号顺序:同一事务里
            # create 每条都 flush,max(episode_number) 随之递增(已实测:已有 1 集时
            # 批量两条得到 2、3)。
            created.append(await episode_service.create(
                session, project_id=project_id, title=item["title"], script_id=None,
                llm_model=llm_model, video_provider=video_provider,
                video_model=video_model, resolution=resolution,
                target_seconds=target_seconds,
                use_keyframes=use_keyframes, seed_screenplay=item["screenplay"],
                autocommit=False))
        project.adaptation_status = AdaptationStatus.COMMITTED.value
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return created
