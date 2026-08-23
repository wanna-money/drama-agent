import asyncio
from pathlib import Path
from drama_agent.workflow.state import DramaState
from drama_agent.services.storage_service import storage_service


async def video_assembler_node(state: DramaState) -> dict:
    project_id = state["project_id"]
    episode_id = state["episode_id"]
    output_dir = storage_service.get_project_output_dir(project_id, episode_id)

    # Collect successful videos in shot order
    shot_order = {s["shot_id"]: i for i, s in enumerate(state["shots"])}
    successful = [
        v
        for v in state["videos"]
        if v["status"] == "succeeded" and v.get("local_path")
    ]
    successful.sort(key=lambda v: shot_order.get(v["shot_id"], 999))

    if not successful:
        return {
            "current_stage": "assembly_failed",
            "error": "No successful videos to assemble",
        }

    # Write ffmpeg concat list (async to avoid blocking event loop)
    concat_file = output_dir / "concat.txt"
    import aiofiles
    async with aiofiles.open(concat_file, "w") as f:
        for v in successful:
            await f.write(f"file '{Path(v['local_path']).absolute()}'\n")

    final_path = output_dir / "final.mp4"

    # Run ffmpeg concat
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(final_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        return {
            "current_stage": "assembly_failed",
            "error": f"ffmpeg error: {stderr.decode()}",
        }

    return {
        "assembled_video_path": str(final_path),
        "current_stage": "completed",
    }
