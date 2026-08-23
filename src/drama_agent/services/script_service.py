"""scripts 仓储:全局剧本库 CRUD + 状态投影。"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.enums import LifecycleStatus
from drama_agent.db.models import Script


def _to_dict(row: Script) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "episode_index": row.episode_index,
        "title": row.title, "genre": row.genre, "source_text": row.source_text,
        "story_analysis": row.story_analysis, "content": row.content,
        "status": row.status, "llm_model": row.llm_model, "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create(
    session: AsyncSession, *, title: str, genre: str = "drama",
    source_text: str | None = None, project_id: str | None = None,
    episode_index: int | None = None, llm_model: str = "",
) -> dict:
    row = Script(
        id=str(uuid.uuid4()), title=title, genre=genre, source_text=source_text,
        project_id=project_id, episode_index=episode_index,
        status=LifecycleStatus.CREATED.value, llm_model=llm_model,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def list_scripts(session: AsyncSession, project_id: str | None = None) -> list[dict]:
    q = select(Script).order_by(Script.created_at.desc())
    if project_id is not None:
        q = q.where(Script.project_id == project_id)
    return [_to_dict(r) for r in (await session.execute(q)).scalars().all()]


async def get(session: AsyncSession, script_id: str) -> dict | None:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    return _to_dict(row) if row else None


async def update(
    session: AsyncSession, script_id: str, *, title: str | None = None, content: str | None = None
) -> dict | None:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return None
    if title is not None:
        row.title = title
    if content is not None:
        row.content = content
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


def _synthesized_draft(screenplay: str) -> dict:
    """未落库的「初稿」条目;created_at=None 标记它是读时合成、不是真实追加过的版本。"""
    return {"screenplay": screenplay, "label": "初稿", "created_at": None}


def _effective_versions(row: Script) -> list[dict]:
    """当前有效版本列表(**只读**,不写库)——「版本 N 存不存在 / 是什么」的唯一权威。
    versions 列尚未产生时(用户还没 revise/edit 过)用当前正文合成版本 0 =「初稿」,
    使 get_status 广播出去的版本与 set_current_version 能选中的版本恒等
    (否则 status 说版本 0 在、/revert 却 422 说它不存在)。"""
    if row.screenplay_versions:
        return list(row.screenplay_versions)
    screenplay = row.content or (row.state_snapshot or {}).get("screenplay")
    return [_synthesized_draft(screenplay)] if screenplay else []


def _seed_versions_if_empty(row: Script, seed_screenplay: str) -> list[dict]:
    """**写路径**专用:versions 为空时以调用方给的 seed_screenplay 种一份「初稿」并落真实
    created_at;否则原样返回现有列表(浅拷贝,调用方重新赋值以触发 JSON 列脏跟踪)。
    与只读的 _effective_versions 分开:这里版本 0 的正文由调用方决定,不由行内容推导。"""
    if row.screenplay_versions:
        return list(row.screenplay_versions)
    return [{
        "screenplay": seed_screenplay,
        "label": "初稿",
        "created_at": datetime.now(UTC).isoformat(),
    }]


async def append_screenplay_version(
    session: AsyncSession, script_id: str, *,
    new_screenplay: str, seed_screenplay: str, label: str,
) -> dict | None:
    """追加一版剧本(AI 改写 / 手动编辑均走此函数);首次调用懒种版本 0 = 初稿。
    label 截断到 80 字,避免版本下拉里的用户输入把 UI 撑爆。"""
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
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
    session: AsyncSession, script_id: str, version_index: int
) -> dict | None:
    """把当前生效版本切到 version_index(供审核态回退用);
    可选版本以 _effective_versions 为准(含读时合成的初稿),越界抛 IndexError,
    由调用方(API 层)映射成 422。"""
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return None
    versions = _effective_versions(row)
    if not (0 <= version_index < len(versions)):
        if versions:
            raise IndexError(
                f"version_index {version_index} out of range (0..{len(versions) - 1})"
            )
        raise IndexError(f"version_index {version_index} out of range (no versions exist)")
    screenplay = versions[version_index]["screenplay"]
    row.screenplay_version_current = version_index
    row.state_snapshot = {**(row.state_snapshot or {}), "screenplay": screenplay}
    await session.commit()
    return {"screenplay": screenplay, "version_index": version_index}


async def reset_for_retry(session: AsyncSession, script_id: str) -> dict | None:
    """重试生成前重置:清空正文/故事分析/错误信息/版本历史,状态置 queued —— 供 SCRIPT_START
    从头重跑(调用方须先清该剧本的 checkpointer 线程,否则图会从旧检查点恢复而非重跑;随后立即入队)。
    版本历史必须一并清空:它属于被丢弃的那次运行,留着会让重跑后的新正文对上旧版本列表
    (_effective_versions 只在 versions 列为空时才按新正文合成初稿)。"""
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return None
    row.content = None
    row.story_analysis = None
    row.error_message = None
    row.screenplay_versions = None
    row.screenplay_version_current = 0
    row.status = LifecycleStatus.QUEUED.value
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def delete(session: AsyncSession, script_id: str) -> bool:
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_status(session: AsyncSession, script_id: str) -> dict | None:
    """Script 状态投影(前端剧本页:进度/审核)。
    正文/故事分析仅在**完成**时落 Script 行;审核暂停(paused-at-review)期间它们在 state_snapshot
    (检查点投影)里、尚未落库,故优先取行、回落快照 —— 保证暂停审核时前端能看到已生成的剧本正文。
    版本历史(screenplay_versions)若尚未产生(用户还没 revise/edit 过),由 _effective_versions
    用当前快照合成一份「初稿」,保证前端版本下拉从审核一开始就有内容可选、且与 revert 口径一致。
    当前版本下标由后端夹紧到 versions 的合法区间(空列表 → 0):
    「(versions, current) 恒自洽」是后端的不变量,前端可直接 versions[current],不该自己兜越界。"""
    row = (await session.execute(
        select(Script).where(Script.id == script_id))).scalar_one_or_none()
    if row is None:
        return None
    snap = row.state_snapshot or {}
    versions = _effective_versions(row)
    current = row.screenplay_version_current or 0
    current = min(current, len(versions) - 1) if versions else 0
    return {
        "id": row.id, "status": row.status, "paused_at": snap.get("paused_at"),
        "title": row.title,
        "content": row.content or snap.get("screenplay"),
        "story_analysis": row.story_analysis or snap.get("story_analysis"),
        "error_message": row.error_message,
        "screenplay_versions": versions,
        "screenplay_version_current": current,
    }
