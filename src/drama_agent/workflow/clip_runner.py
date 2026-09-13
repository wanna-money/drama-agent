"""单支散片的执行:调视频模型 → 落地 → 记账 → 写根产物。

跑在 worker 的 job 里,故 wait_for_task 阻塞是允许的(不占 HTTP 请求)。
与图无关:散片不进 LangGraph,没有 thread、没有 checkpoint。
"""
import structlog

from drama_agent.db import session as db_session
from drama_agent.services import artifact_service, clip_service, usage_service
from drama_agent.services.public_storage import (
    PublicStorageUnavailable,
    get_public_storage,
)
from drama_agent.services.ref_delivery import deliver_refs
from drama_agent.services.storage_service import storage_service
from drama_agent.services.video_refs import RefAudio, RefImage, RefVideo
from drama_agent.services.video_service import video_service

logger = structlog.get_logger()


async def run_clip(clip_id: str) -> None:
    """执行一支散片。

    终态由本函数自己落:传输层异常时**先标 failed 再抛**(交 job 判死)。
    只抛不标的话 worker 标的是 job 行 —— 它按 job.episode_id 去查 Episode,
    而这里那一列装的是 clip_id,查不到就静默 no-op,散片会永远停在 running。
    """
    async with db_session.AsyncSessionLocal() as s:
        clip = await clip_service.get(s, clip_id)
    if clip is None:
        logger.warning("run_clip: clip 不存在", clip_id=clip_id)
        return

    await clip_service.mark_running(clip_id)
    output_dir = storage_service.get_project_output_dir(clip["project_id"], "clips")

    try:
        # 两个参数都要传:只给 protocol 会退回 settings 的全局 key,
        # 用户在「模型管理」为该 provider 配的凭证与 base_url 就不生效。
        provider = video_service.get_provider(
            clip["video_provider"], clip["video_model"] or None)

        refs = [RefImage(**r) for r in (clip["references_json"] or [])]
        audios = [RefAudio(**a) for a in (clip["audio_refs_json"] or [])]
        videos = [RefVideo(**v) for v in (clip["video_refs_json"] or [])]
        # 内联/现签后的形态只用于发送;产物树存原始语义(base64 会撑爆 DB,
        # 签名 URL 会过期)
        sent_refs, sent_audio, sent_videos = await deliver_refs(refs, audios, videos)

        task_id = await provider.create_task(
            prompt=clip["prompt"],
            duration=clip["duration"],
            # 比例与分辨率都不在此兜底:两者由建散片时的表单保证非空
            # (`videoInitValues` 读后端下发的 default,拿不到时退到自己的兜底)。
            # 只兜其中一个会让读代码的人以为另一个是漏的。
            ratio=clip["aspect_ratio"],
            resolution=clip["resolution"],
            negative_prompt=clip["negative_prompt"] or "",
            references=sent_refs or None,
            audio_refs=sent_audio or None,
            video_refs=sent_videos or None,
            task_type=clip.get("task_type") or "",
        )
        result = await provider.wait_for_task(task_id, poll_interval=15, max_wait=600)
    except PublicStorageUnavailable as e:
        # 这条要单独接:它的可行动信息是"去配置存储",而裹进通用分支后
        # 用户看到的是一串类名,与该做什么无关。
        await clip_service.mark_failed(clip_id, f"参考视频需要公网存储:{e}")
        raise
    except Exception as e:
        await clip_service.mark_failed(clip_id, f"{type(e).__name__}: {e}")
        raise

    if result.status != "succeeded" or not result.video_url:
        await clip_service.mark_failed(clip_id, result.error or "生成失败(平台未给出原因)")
        return

    try:
        local_path = output_dir / f"{clip_id}.mp4"
        await storage_service.download_file(result.video_url, local_path)
    except Exception as e:
        await clip_service.mark_failed(clip_id, f"下载失败: {type(e).__name__}: {e}")
        raise

    await clip_service.mark_completed(
        clip_id, task_id=task_id, video_url=result.video_url,
        local_path=str(local_path), seed=result.seed,
        revised_prompt=result.revised_prompt,
        # 编辑任务提交的是 -1,真实时长只有平台回传值能给出。
        # **必须在记账之前落**:-1 会让 record_video 算出负数秒。
        duration=result.duration,
    )
    # 记账要用真实秒数:提交值可能是 -1。平台没回真实时长时退回提交值,
    # 但提交值本身也可能是 -1(编辑任务且平台未回传)—— 夹到 0
    # (记 0 秒比记 -1 秒诚实:我们确实不知道)。
    billed_seconds = max(0, result.duration or int(clip["duration"] or 0))

    # 传一份到公网,让这支片之后能被引用为「视频编辑/延长」的输入。
    # **旁路** —— 它失败不得把一支已生成成功、已落本地的片翻成失败;
    # 后果只是"这支片暂时不能被二次创作"。
    # 平台回传的 video_url 24 小时就失效,故不能拿它当长期引用。
    try:
        content = local_path.read_bytes()
        key = await get_public_storage().put(content, f"{clip_id}.mp4")
        await clip_service.set_storage_key(clip_id, key)
    except PublicStorageUnavailable:
        # 未配存储是常态(默认就没配),不值一条 warning
        pass
    except Exception as e:  # noqa: BLE001 — 上传失败不阻断
        logger.warning("clip 公网副本上传失败", clip_id=clip_id, error=str(e))

    # 以下两项是旁路:它们失败不得把已成功的散片翻成失败。
    try:
        await usage_service.record_video(
            provider=clip["video_provider"], model=clip["video_model"],
            seconds=billed_seconds,
            entity_id=clip_id, project_id=clip["project_id"],
        )
    except Exception as e:  # noqa: BLE001 — 记账失败不阻断
        logger.warning("clip usage 记账失败", clip_id=clip_id, error=str(e))

    # 血统数据先落库:散片的产物树是单根 + 若干动作子节点。
    # episode_id 留空、shot_id 用 clip_id —— 散片不属于任何集。
    #
    # **现在还读不出来**:产物树的读取与动作端点都按 `/api/episodes/{episode_id}/...`
    # 寻址,而 URL 里的空路径段返回 404(不会被当作 episode_id="" 匹配)。
    # 要让 rerun / 改参重生 / 升清对散片可用,须新增一套按 project_id 寻址的端点;
    # 那时这里攒下的历史产物也能一并列出。**不要因为"读不到"就把这段删掉。**
    try:
        async with db_session.AsyncSessionLocal() as s:
            await artifact_service.create_root(
                s, episode_id="", project_id=clip["project_id"], shot_id=clip_id,
                provider=clip["video_provider"], model=clip["video_model"],
                resolution=clip["resolution"], aspect_ratio=clip["aspect_ratio"],
                # 真实时长(编辑任务提交 -1 时,这里必须是回传值)
                duration=billed_seconds, task_id=task_id,
                video_url=result.video_url, local_path=str(local_path),
                prompt_text=clip["prompt"],
                # 负向提示单独存:它已折进送出的 prompt,重放时若从 prompt_text
                # 再折一次就会双份追加
                negative_prompt=clip["negative_prompt"] or None,
                seed=result.seed, revised_prompt=result.revised_prompt,
                references=clip["references_json"] or None,
                audio_refs=clip["audio_refs_json"] or None,
            )
    except Exception as e:  # noqa: BLE001 — 产物树写入是旁路
        logger.warning("clip 产物写入失败", clip_id=clip_id, error=str(e))
