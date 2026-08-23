"""video_artifacts 仓储：写根产物、建子产物、查产物树。"""
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from drama_agent.db.models import VideoArtifact


def _to_dict(row: VideoArtifact) -> dict:
    return {
        "id": row.id,
        "episode_id": row.episode_id,
        "project_id": row.project_id,
        "shot_id": row.shot_id,
        "parent_id": row.parent_id,
        "provider": row.provider,
        "model": row.model,
        "resolution": row.resolution,
        "duration": row.duration,
        "action": row.action,
        "task_id": row.task_id,
        "video_url": row.video_url,
        "local_path": row.local_path,
        "prompt_text": row.prompt_text,
        "references_json": row.references_json,
        "audio_refs_json": row.audio_refs_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_root(
    session: AsyncSession, *, episode_id: str, shot_id: str, provider: str, model: str,
    resolution: str, duration: int, task_id: str, video_url: str | None,
    local_path: str | None, prompt_text: str | None, project_id: str = "",
    references: list[dict] | None = None, audio_refs: list[dict] | None = None,
) -> dict:
    row = VideoArtifact(
        id=str(uuid.uuid4()), episode_id=episode_id, project_id=project_id,
        shot_id=shot_id, parent_id=None,
        provider=provider, model=model, resolution=resolution, duration=duration,
        action="generate", task_id=task_id, video_url=video_url,
        local_path=local_path, prompt_text=prompt_text, references_json=references,
        audio_refs_json=audio_refs,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def create_child(session: AsyncSession, parent_artifact: dict, new_fields: dict) -> dict:
    row = VideoArtifact(id=str(uuid.uuid4()), **{
        "episode_id": new_fields.get("episode_id", parent_artifact.get("episode_id", "")),
        "project_id": new_fields.get("project_id", parent_artifact.get("project_id", "")),
        "shot_id": new_fields["shot_id"],
        "parent_id": new_fields.get("parent_id", parent_artifact["id"]),
        "provider": new_fields["provider"],
        "model": new_fields.get("model", ""),
        "resolution": new_fields["resolution"],
        "duration": new_fields["duration"],
        "action": new_fields["action"],
        "task_id": new_fields.get("task_id", ""),
        "video_url": new_fields.get("video_url"),
        "local_path": new_fields.get("local_path"),
        "prompt_text": new_fields.get("prompt_text"),
        # 子产物沿用父的参考图(除非动作显式改写),使后续 rerun 仍能重放一致参考
        "references_json": new_fields.get("references_json", parent_artifact.get("references_json")),
        "audio_refs_json": new_fields.get("audio_refs_json", parent_artifact.get("audio_refs_json")),
    })
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_dict(row)


async def list_by_shot(session: AsyncSession, episode_id: str, shot_id: str) -> list[dict]:
    result = await session.execute(
        select(VideoArtifact)
        .where(VideoArtifact.episode_id == episode_id, VideoArtifact.shot_id == shot_id)
        .order_by(VideoArtifact.created_at.asc())
    )
    return [_to_dict(r) for r in result.scalars().all()]


async def get(session: AsyncSession, artifact_id: str) -> dict | None:
    result = await session.execute(
        select(VideoArtifact).where(VideoArtifact.id == artifact_id)
    )
    row = result.scalar_one_or_none()
    return _to_dict(row) if row else None
