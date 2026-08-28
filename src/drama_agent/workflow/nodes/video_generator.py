import logging
from dataclasses import asdict

from drama_agent.workflow.state import DramaState, VideoDict
from drama_agent.services.video_service import video_service
from drama_agent.services.video_refs import RefImage, RefAudio, cap_audio_refs
from drama_agent.services.ref_delivery import inline_local_refs
from drama_agent.services.storage_service import storage_service
from drama_agent.db.session import AsyncSessionLocal
from drama_agent.services import artifact_service
from drama_agent.services import subject_ref_service
from drama_agent.services import usage_service

logger = logging.getLogger(__name__)


async def _audio_refs_for_shot(project_id: str, shot: dict) -> list[RefAudio]:
    """镜头出场角色各取各自音色(voice_key);无音色/join 失败跳过,不阻断。"""
    from drama_agent.services import character_entity_service as ce
    out: list[RefAudio] = []
    for name in shot.get("characters", []):
        try:
            ch = await ce.get_character_by_name(project_id, name)
            if ch is None or not getattr(ch, "voice_key", None):
                continue
            out.append(RefAudio(url=f"/api/characters/voice/{ch.voice_key}", subject_name=name))
        except Exception:  # noqa: BLE001 — 单角色解析失败不阻断
            continue
    return out


async def _resolve_audio_refs(
    provider_name: str, project_id: str, shot: dict, references: list[RefImage]
) -> list[RefAudio]:
    """能力门控(supports_audio_reference)+ 上限截断(max_reference_audios)+ 互斥降级。"""
    from drama_agent import provider as provider_pkg
    try:
        _, vmodel = provider_pkg.provider_registry.resolve_model(provider_name)
    except Exception:  # noqa: BLE001 — 未知 provider → 不挂音频
        return []
    if vmodel is None or not vmodel.supports_audio_reference:
        return []
    audio_refs = await _audio_refs_for_shot(project_id, shot)
    audio_refs = cap_audio_refs(audio_refs, vmodel.max_reference_audios, provider_name)
    if audio_refs and not references:
        logger.warning("shot has audio but no image refs; dropping audio (provider=%s)", provider_name)
        return []
    return audio_refs


async def video_generator_node(state: DramaState) -> dict:
    provider_name = state.get("video_provider", "seedance")
    provider = video_service.get_provider(provider_name)
    resolution = state.get("resolution")
    project_id = state["project_id"]
    episode_id = state["episode_id"]
    output_dir = storage_service.get_project_output_dir(project_id, episode_id)

    # Use approved/edited prompts
    prompts = state["prompts"]
    shots = {s["shot_id"]: s for s in state["shots"]}
    videos: list[VideoDict] = []

    # Build map of existing videos (resume support)
    existing = {
        v["shot_id"]: v
        for v in state.get("videos", [])
        if v.get("status") == "succeeded"
    }

    last_frame_url: str | None = None

    for prompt in prompts:
        shot_id = prompt["shot_id"]

        # Skip already-generated shots
        if shot_id in existing:
            videos.append(existing[shot_id])
            last_frame_url = existing[shot_id].get("last_frame_url")
            continue

        shot: dict = dict(shots.get(shot_id) or {})

        # Final prompt text (use human-edited if available)
        final_prompt = prompt.get("edited_prompt") or prompt["prompt_text"]

        # Final negative prompt (use human-edited if present — is not None, NOT truthy,
        # so an intentional "" clears the negative prompt instead of falling back to the original)
        edited_neg = prompt.get("edited_negative_prompt")
        final_negative_prompt = (
            edited_neg if edited_neg is not None else prompt.get("negative_prompt", "")
        )

        # 组装 provider 无关的语义参考图:首帧连贯(关键帧/上一镜末帧)+ 角色 subject。
        # subject 一律走 subject_ref_service(唯一权威),此处不再另起一条取图路径。
        references: list[RefImage] = []
        keyframe_url = prompt.get("keyframe_url")
        prompt_ref = prompt.get("reference_image_url")
        if keyframe_url:
            references.append(RefImage(url=keyframe_url, kind="first_frame"))
        elif prompt_ref:
            references.append(RefImage(url=prompt_ref, kind="first_frame"))
        elif last_frame_url:
            references.append(RefImage(url=last_frame_url, kind="first_frame"))
        references.extend(await subject_ref_service.subject_refs(
            project_id, shot, state.get("look_assignments") or {}))

        audio_refs = await _resolve_audio_refs(provider_name, project_id, shot, references)
        # 送达:本地图/音 ref → data URI(顺带修 subject 相对 URL 外部取不到的隐患)。
        # 内联后的 refs 仅用于发给 provider;产物树仍存原始语义 refs(避免 base64 撑爆 DB)。
        sent_refs, sent_audio = await inline_local_refs(references, audio_refs)

        video: VideoDict = {
            "shot_id": shot_id,
            "task_id": "",
            "status": "queued",
            "video_url": None,
            "last_frame_url": None,
            "local_path": None,
            "error": None,
        }

        default_res = {"seedance": "1080p", "seedance-2.5": "1080p", "minimax": "768P"}.get(
            provider_name, "720P")
        duration = shot.get("duration_seconds", 5)
        try:
            task_id = await provider.create_task(
                prompt=final_prompt,
                duration=duration,
                ratio="16:9",
                resolution=resolution or default_res,
                negative_prompt=final_negative_prompt,
                references=sent_refs,
                audio_refs=sent_audio,
            )

            video["task_id"] = task_id
            video["status"] = "running"

            # Wait for completion
            result = await provider.wait_for_task(
                task_id, poll_interval=15, max_wait=600
            )

            if result.status == "succeeded" and result.video_url:
                # Download video locally
                local_path = output_dir / f"{shot_id}.mp4"
                await storage_service.download_file(result.video_url, local_path)
                video["status"] = "succeeded"
                video["video_url"] = result.video_url
                video["last_frame_url"] = result.last_frame_url
                video["local_path"] = str(local_path)
                last_frame_url = result.last_frame_url

                # 记账旁路:seconds 转换失败也不得把已成功的分镜翻成 failed。
                try:
                    seconds = int(duration or 0)
                except (TypeError, ValueError):
                    seconds = 0
                await usage_service.record_video(
                    provider=provider_name,
                    model=state.get("video_model", ""),
                    seconds=seconds,
                )

                # Record the root artifact for the capability tree (non-blocking).
                try:
                    async with AsyncSessionLocal() as session:
                        await artifact_service.create_root(
                            session,
                            episode_id=episode_id,
                            project_id=project_id,
                            shot_id=shot_id,
                            provider=provider_name,
                            model=state.get("video_model", ""),
                            resolution=resolution or "",
                            duration=duration,
                            task_id=task_id,
                            video_url=result.video_url,
                            local_path=str(local_path),
                            prompt_text=final_prompt,
                            references=[asdict(r) for r in references] or None,
                            audio_refs=[asdict(a) for a in audio_refs] or None,
                        )
                except Exception:
                    pass  # artifact tree write must not break the main flow
            else:
                video["status"] = "failed"
                video["error"] = result.error or "Unknown error"
                last_frame_url = None

        except Exception as e:
            video["status"] = "failed"
            video["error"] = str(e)
            last_frame_url = None

        videos.append(video)

    return {
        "videos": videos,
        "current_stage": "videos_generated",
    }
