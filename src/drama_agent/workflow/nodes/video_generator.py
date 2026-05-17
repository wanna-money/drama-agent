import asyncio
from pathlib import Path
from drama_agent.workflow.state import DramaState, VideoDict
from drama_agent.services.video_service import video_service
from drama_agent.services.storage_service import storage_service


async def video_generator_node(state: DramaState) -> dict:
    provider_name = state.get("video_provider", "seedance")
    provider = video_service.get_provider(provider_name)
    project_id = state["project_id"]
    output_dir = storage_service.get_project_output_dir(project_id)

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

        shot = shots.get(shot_id, {})

        # Final prompt text (use human-edited if available)
        final_prompt = prompt.get("edited_prompt") or prompt["prompt_text"]

        # Continuity: chain last frame to next shot's first frame
        ref_image = prompt.get("reference_image_url")
        ref_role = prompt.get("reference_role", "first_frame")
        if last_frame_url and ref_role == "first_frame":
            ref_image = last_frame_url

        video: VideoDict = {
            "shot_id": shot_id,
            "task_id": "",
            "status": "queued",
            "video_url": None,
            "last_frame_url": None,
            "local_path": None,
            "error": None,
        }

        try:
            # Create task
            if provider_name == "seedance":
                task_id = await provider.create_task(
                    prompt=final_prompt,
                    duration=shot.get("duration_seconds", 5),
                    ratio="16:9",
                    resolution="1080p",
                    reference_image_url=ref_image,
                    reference_role=ref_role if ref_image else None,
                    negative_prompt=prompt.get("negative_prompt", ""),
                )
            else:
                task_id = await provider.create_task(
                    prompt=final_prompt,
                    duration=shot.get("duration_seconds", 5),
                    ratio="16:9",
                    resolution="720P",
                    negative_prompt=prompt.get("negative_prompt", ""),
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
