import logging
from dataclasses import asdict

from drama_agent.workflow.state import DramaState, VideoDict
from drama_agent.services.video_service import video_service
from drama_agent.services.video_refs import RefImage, RefAudio, cap_audio_refs
from drama_agent.services.ref_delivery import inline_local_refs
from drama_agent.services.storage_service import storage_service
from drama_agent.services.video_trim import trim_to_narrative_duration
from drama_agent.db.session import AsyncSessionLocal
from drama_agent.services import artifact_service
from drama_agent.services import subject_ref_service
from drama_agent.services import usage_service

logger = logging.getLogger(__name__)


async def report_progress(
    episode_id: str, stage: str, *, videos: list | None = None, project_id: str = "",
) -> None:
    """把中途进度写进投影 + 事件,使这一步在界面上可观测。

    本节点串行跑十几支视频、耗时十几分钟,若只在最后返回一次增量:
      · 左栏整段时间停在上一步(阶段词表里没有"正在生成");
      · 看不出跑到第几支;
      · 中途崩溃后重跑从第一支开始 —— resume 的跳过判据是 videos[].status=="succeeded",
        而它们从没落库。
    进度上报是旁路:写失败不得中断出片(规范 6)。
    """
    from drama_agent.db import session as db_session
    from drama_agent.db.enums import EventType, LifecycleStatus
    from drama_agent.db.models import Episode
    from drama_agent.services import event_service
    from sqlalchemy import select

    try:
        async with db_session.AsyncSessionLocal() as db:
            row = (await db.execute(
                select(Episode).where(Episode.id == episode_id)
            )).scalar_one_or_none()
            if row is None:
                return
            snap = dict(row.state_snapshot or {})
            snap["current_stage"] = stage
            if videos is not None:
                snap["videos"] = videos
            row.state_snapshot = snap
            row.status = LifecycleStatus.RUNNING.value
            await db.flush()
            await event_service.append_event(
                db, episode_id, EventType.STAGE_CHANGE,
                {"current_stage": stage,
                 "videos_done": len([v for v in (videos or [])
                                     if v.get("status") == "succeeded"])},
                project_id=project_id or row.project_id,
            )
    except Exception:  # noqa: BLE001 — 进度上报是旁路,不得拖垮出片
        logger.warning("video progress report failed (stage=%s)", stage, exc_info=True)


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


def _default_resolution(model_ref: str) -> str:
    """该模型声明的默认分辨率;解析不到时用一个保守兜底(所有内置模型都支持 720P)。"""
    from drama_agent import provider as provider_pkg
    try:
        _, mdl = provider_pkg.provider_registry.resolve_model(model_ref)
    except Exception:  # noqa: BLE001 — 解析不到不阻断出片
        return "720P"
    return mdl.default_resolution or "720P"


async def video_generator_node(state: DramaState) -> dict:
    provider_name = state.get("video_provider", "seedance")
    # 带上 video_model:provider 的凭证/base_url 由注册表按模型解析(规范 4),
    # 不传就只能退回 settings 的全局 key —— 用户在「模型管理」配的那条就不生效了。
    provider = video_service.get_provider(provider_name, state.get("video_model") or None)
    resolution = state.get("resolution")
    # 分辨率默认值的权威是 Model 声明(规范 4)。按 provider 名查一张硬编码表会与声明
    # 分叉,且新增模型时要记得改那张表 —— 那正是"同一规则两处住所"。
    default_res = _default_resolution(state.get("video_model") or provider_name)
    # 画面比例来自集级配置(短剧多为竖屏);写死会让所有集只能出一种比例
    ratio = state.get("aspect_ratio") or "9:16"
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

    # 开跑前先落一次"正在生成":这是整条流水线最慢的一步,没有这个阶段界面就只能
    # 停在上一步(见 pipeline_steps 的 video 步词表)。
    await report_progress(episode_id, "videos_generating",
                         videos=list(existing.values()), project_id=project_id)

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

        duration = shot.get("duration_seconds", 5)
        try:
            task_id = await provider.create_task(
                prompt=final_prompt,
                duration=duration,
                ratio=ratio,
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
                # 真实叙事时长明显短于生成时长(如一次击中/爆炸)时,把平台按下限生成
                # 出来的多余尾段裁掉——那段尾巴是模型为撑满时长而拉长/放慢/静止的
                # 填充,是"成片像 PPT 一样卡顿"的直接成因之一。只裁本地文件,不影响
                # provider 那边的原始产出与 revised_prompt/seed 等回传信息。
                narrative_duration = shot.get("narrative_duration_seconds")
                if narrative_duration:
                    await trim_to_narrative_duration(local_path, int(narrative_duration))
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
                            aspect_ratio=ratio,
                            duration=duration,
                            task_id=task_id,
                            video_url=result.video_url,
                            local_path=str(local_path),
                            prompt_text=final_prompt,
                            # 负向提示单独存:它已折进送出的 prompt,重放时若从 prompt_text
                            # 再折一次就会双份追加
                            negative_prompt=final_negative_prompt or None,
                            seed=result.seed,
                            revised_prompt=result.revised_prompt,
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
        # 每支落一次:界面能看到 n/总数,且崩溃后重跑能跳过已成功的那些
        await report_progress(episode_id, "videos_generating",
                             videos=videos, project_id=project_id)

    return {
        "videos": videos,
        "current_stage": "videos_generated",
    }
