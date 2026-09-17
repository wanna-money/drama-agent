"""episodes 仓储:集 CRUD + 项目状态聚合(纯函数,不落库)。

一个 Project 含多个 Episode;每集是一条独立流水线(thread=episode.id)。
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Episode
from drama_agent.db.enums import LifecycleStatus


def _to_dict(row: Episode) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "episode_number": row.episode_number,
        "title": row.title,
        "story_id": row.story_id,
        "script_id": row.script_id,
        "entry_mode_at_start": row.entry_mode_at_start,
        "target_seconds": row.target_seconds,
        "status": row.status,
        "llm_model": row.llm_model,
        "video_provider": row.video_provider,
        "video_model": row.video_model,
        "resolution": row.resolution,
        "aspect_ratio": row.aspect_ratio,
        "state_snapshot": row.state_snapshot,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def seeded_screenplay(row: Episode) -> str:
    """本集自带的剧本正文(改编切片建集时种入版本 0);没有则空串。"""
    versions = row.screenplay_versions or []
    if not versions:
        return ""
    return versions[row.screenplay_version_current or 0].get("screenplay", "") or ""


def entry_mode(row: Episode, script_content: str | None) -> str:
    """本集从哪儿起跑:"from_script"(已有正文 → 直达分镜)/ "from_story"(只有原文)。

    判据是**开拍那一刻有没有正文**,不是有没有 script_id:有方案而方案正文为空时仍要跑
    剧本步(正文正是流水线要产出的东西)。这是唯一权威(规范 4):runner 用它决定
    screenplay_approved,status 端点用它决定流水线要不要展示剧本三步。两处各判一次必然
    分叉:一边跑剧本步、另一边不显示它,或反之显示永远走不到的死步骤。

    **它必须在整集生命周期内恒定**:若改看"当前有没有正文",从故事开跑的集在剧本产出后
    就会翻转成 from_script,左栏的剧本四步在流程跑到一半时凭空消失(实测过)。
    故已开拍的集一律以 entry_mode_at_start 记下的值为准,只有未开拍时才现算。
    """
    if row.entry_mode_at_start:
        return row.entry_mode_at_start
    has_text = bool(seeded_screenplay(row).strip() or (script_content or "").strip())
    return "from_script" if has_text else "from_story"


def aggregate_project_status(episode_statuses: list[str]) -> str:
    """按各集状态聚合出项目展示态(取最活跃优先)。纯函数。"""
    s = set(episode_statuses)
    if not s:
        return "empty"
    if s & {LifecycleStatus.RUNNING.value, LifecycleStatus.QUEUED.value}:
        return "running"
    if LifecycleStatus.PAUSED.value in s:
        return "paused"
    if episode_statuses and all(st == LifecycleStatus.COMPLETED.value for st in episode_statuses):
        return "completed"
    if LifecycleStatus.FAILED.value in s:
        return "partial_failed"
    return "running"  # 兜底:有集但非上述终态,视为进行中


async def create(
    session: AsyncSession, *, project_id: str, title: str, story_id: str,
    llm_model: str, video_provider: str, video_model: str, resolution: str,
    script_id: str | None = None,
    aspect_ratio: str = "9:16", episode_number: int | None = None,
    target_seconds: int = 120,
    use_keyframes: bool = False, keyframe_image_model: str = "",
    seed_screenplay: str | None = None, autocommit: bool = True,
) -> dict:
    """建一集。**story_id 必填**:集是一次制作运行,输入是原文。

    script_id 可空,只记"起始剧本方案是哪个"(溯源);从一段故事开跑时没有方案。
    有正文 → 图内直达分镜;只有原文 → 从故事分析起跑(见 runner._build_initial_state)。
    episode_number 不传则自动取 project 下 max+1。
    seed_screenplay 传了(改编切片)则直接种为该集初始剧本版本 0。
    autocommit=False 时只 flush,由调用方统一 commit(批量建集要"全成或全不成")。
    """
    if not (story_id or "").strip():
        # 业务必填,在此强制(DB 上可空只为兼容旧行)。没有原文的集跑不起来:
        # 分析/阵容/原文都从 Story 取,缺了它流水线第一步就没有输入。
        raise ValueError("story_id 不能为空:集必须绑定一段原文")
    if episode_number is None:
        current_max = (await session.execute(
            select(func.coalesce(func.max(Episode.episode_number), 0))
            .where(Episode.project_id == project_id)
        )).scalar() or 0
        episode_number = current_max + 1
    row = Episode(
        id=str(uuid.uuid4()), project_id=project_id, episode_number=episode_number,
        title=title, story_id=story_id, script_id=script_id,
        target_seconds=target_seconds, status=LifecycleStatus.CREATED.value,
        llm_model=llm_model, video_provider=video_provider,
        video_model=video_model, resolution=resolution, aspect_ratio=aspect_ratio,
        use_keyframes=use_keyframes, keyframe_image_model=keyframe_image_model,
        screenplay_versions=(
            [{"screenplay": seed_screenplay, "label": "分集剧本",
              "created_at": datetime.now(UTC).isoformat()}] if seed_screenplay else None),
        screenplay_version_current=0,
    )
    session.add(row)
    if autocommit:
        await session.commit()
        await session.refresh(row)
    else:
        # 批量建集:由调用方统一 commit,保证"全成或全不成"
        await session.flush()
    return _to_dict(row)


async def get(session: AsyncSession, episode_id: str) -> dict | None:
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id)
    )).scalar_one_or_none()
    return _to_dict(row) if row else None


async def list_by_project(session: AsyncSession, project_id: str) -> list[dict]:
    rows = (await session.execute(
        select(Episode).where(Episode.project_id == project_id)
        .order_by(Episode.episode_number.asc())
    )).scalars().all()
    return [_to_dict(r) for r in rows]


async def project_status(session: AsyncSession, project_id: str) -> str:
    """读该项目所有集状态并聚合。"""
    rows = (await session.execute(
        select(Episode.status).where(Episode.project_id == project_id)
    )).scalars().all()
    return aggregate_project_status(list(rows))


# ── 剧本版本树(从 script_service 搬来,实体换成 Episode) ──────────────────
# 剧本审核阶段的 AI 改写/手动编辑/回退都作用在 Episode.screenplay_versions 上。
# 读侧与写侧分开:读侧(_effective_versions)在无数据时按当前正文合成"初稿";
# 写侧(_seed_versions_if_empty)的 version 0 正文由调用方给,不从行推导。

def _effective_versions(row: Episode) -> list[dict]:
    """读侧权威:版本是否存在以这里为准;无数据则从当前正文合成一条"初稿"。"""
    if row.screenplay_versions:
        return list(row.screenplay_versions)
    base = (row.state_snapshot or {}).get("screenplay") or ""
    if not base:
        return []
    return [{"screenplay": base, "label": "初稿", "created_at": None}]


def _seed_versions_if_empty(row: Episode, seed_screenplay: str) -> list[dict]:
    """写侧的初稿合成:version 0 的正文由调用方提供,不从 row 读。"""
    if row.screenplay_versions:
        return list(row.screenplay_versions)
    return [{"screenplay": seed_screenplay, "label": "初稿",
             "created_at": datetime.now(UTC).isoformat()}]


async def append_screenplay_version(
    session: AsyncSession, episode_id: str, *,
    new_screenplay: str, seed_screenplay: str, label: str,
) -> dict | None:
    """追加一版剧本(AI 改写 / 手动编辑);首次调用懒种 version 0 = 初稿。
    label 截断到 80 字,避免版本下拉里的用户输入把 UI 撑爆。"""
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if row is None:
        return None
    versions = _seed_versions_if_empty(row, seed_screenplay)
    versions.append({
        "screenplay": new_screenplay,
        "label": (label or "").strip()[:80] or "改写",
        "created_at": datetime.now(UTC).isoformat(),
    })
    row.screenplay_versions = versions
    row.screenplay_version_current = len(versions) - 1
    row.state_snapshot = {**(row.state_snapshot or {}), "screenplay": new_screenplay}
    await session.commit()
    return {
        "screenplay": new_screenplay,
        "version_index": row.screenplay_version_current,
        "versions_len": len(versions),
    }


async def set_current_version(
    session: AsyncSession, episode_id: str, version_index: int,
) -> dict | None:
    """把当前生效版本切到 version_index(供审核态回退用);
    可选版本以 _effective_versions 为准,越界抛 IndexError,由调用方(API 层)映射成 422。"""
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if row is None:
        return None
    versions = _effective_versions(row)
    if not 0 <= version_index < len(versions):
        raise IndexError(f"版本号 {version_index} 超出范围(共 {len(versions)} 版)")
    row.screenplay_version_current = version_index
    chosen = versions[version_index]["screenplay"]
    row.state_snapshot = {**(row.state_snapshot or {}), "screenplay": chosen}
    await session.commit()
    return {"screenplay": chosen, "version_index": version_index}


# ── 分镜版本树(与上面的剧本版本树同构,实体字段换成 shots) ──────────────────
# storyboard_director 每次(重新)生成都追加一版,而不是覆盖 —— 否则"退回重新
# 生成"会让已看过、可能更满意的上一版分镜无法再对比或恢复(见 screenplay 版本树
# 同一动机)。写侧在图节点内直接调用(见 storyboard_director_node),读侧/回退侧
# 与剧本对称,供 API 层的 /storyboard/revert 使用。

def _effective_shots_versions(row: Episode) -> list[dict]:
    """读侧权威:版本是否存在以这里为准;无数据则从当前快照的 shots 合成一条"初稿"。"""
    if row.shots_versions:
        return list(row.shots_versions)
    shots = (row.state_snapshot or {}).get("shots") or []
    if not shots:
        return []
    return [{"shots": shots, "label": "初稿", "created_at": None}]


async def append_shots_version_db(
    session: AsyncSession, episode_id: str, *, shots: list[dict], label: str,
) -> dict | None:
    """追加一版分镜。label 截断到 80 字(与 append_screenplay_version 同例,
    避免版本下拉里的意见原文把 UI 撑爆)。"""
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if row is None:
        return None
    versions = list(row.shots_versions) if row.shots_versions else []
    versions.append({
        "shots": shots,
        "label": (label or "").strip()[:80] or "重新生成",
        "created_at": datetime.now(UTC).isoformat(),
    })
    row.shots_versions = versions
    row.shots_version_current = len(versions) - 1
    await session.commit()
    return {
        "version_index": row.shots_version_current,
        "versions_len": len(versions),
    }


async def set_current_shots_version(
    session: AsyncSession, episode_id: str, version_index: int,
) -> dict | None:
    """把当前生效分镜版本切到 version_index,返回该版本的 shots 供调用方写回图状态。
    越界抛 IndexError,由调用方(API 层)映射成 422。"""
    row = (await session.execute(
        select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if row is None:
        return None
    versions = _effective_shots_versions(row)
    if not 0 <= version_index < len(versions):
        raise IndexError(f"版本号 {version_index} 超出范围(共 {len(versions)} 版)")
    row.shots_version_current = version_index
    chosen = versions[version_index]["shots"]
    row.state_snapshot = {**(row.state_snapshot or {}), "shots": chosen}
    await session.commit()
    return {"shots": chosen, "version_index": version_index}
