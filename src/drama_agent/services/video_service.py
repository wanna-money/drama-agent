import asyncio
import httpx
from typing import Any
from drama_agent.config import settings


class VideoTaskResult:
    def __init__(
        self,
        task_id: str,
        status: str,
        video_url: str | None = None,
        last_frame_url: str | None = None,
        error: str | None = None,
    ):
        self.task_id = task_id
        self.status = status
        self.video_url = video_url
        self.last_frame_url = last_frame_url
        self.error = error


class SeedanceVideoService:
    def __init__(self):
        from volcenginesdkarkruntime import AsyncArk

        self._client = AsyncArk(api_key=settings.ark_api_key)
        self.model = settings.seedance_endpoint_id or "doubao-seedance-2.0-pro"

    async def create_task(
        self,
        prompt: str,
        duration: int = 5,
        ratio: str = "16:9",
        resolution: str = "1080p",
        reference_image_url: str | None = None,
        reference_role: str | None = None,
        negative_prompt: str = "",
    ) -> str:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if reference_image_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": reference_image_url},
                    "role": reference_role or "first_frame",
                }
            )

        create_result = await self._client.content_generation.tasks.create(
            model=self.model,
            content=content,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            return_last_frame=True,
        )
        return create_result.id

    async def get_task(self, task_id: str) -> VideoTaskResult:
        task = await self._client.content_generation.tasks.get(task_id=task_id)
        status = task.status
        video_url = task.content.video_url if task.content else None
        last_frame_url = task.content.last_frame_url if task.content else None
        error = getattr(task, "error", None)
        if error and not isinstance(error, str):
            error = str(error)
        return VideoTaskResult(
            task_id=task_id,
            status=status,
            video_url=video_url,
            last_frame_url=last_frame_url,
            error=error,
        )

    async def wait_for_task(
        self,
        task_id: str,
        poll_interval: int = 15,
        max_wait: int = 600,
    ) -> VideoTaskResult:
        elapsed = 0
        while elapsed < max_wait:
            result = await self.get_task(task_id)
            if result.status in ("succeeded", "failed", "cancelled"):
                return result
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(
            f"Seedance task {task_id} did not complete within {max_wait}s"
        )


class BailianVideoService:
    BASE_URL = "https://dashscope.aliyuncs.com/api/v1"
    MODEL = "wan2.7-t2v-2026-04-25"

    async def create_task(
        self,
        prompt: str,
        duration: int = 5,
        ratio: str = "16:9",
        resolution: str = "720P",
        negative_prompt: str = "",
        **kwargs,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        body = {
            "model": self.MODEL,
            "input": {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
            },
            "parameters": {
                "resolution": resolution,
                "ratio": ratio,
                "duration": duration,
                "prompt_extend": True,
                "watermark": False,
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.BASE_URL}/services/aigc/video-generation/video-synthesis",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        return data["output"]["task_id"]

    async def get_task(self, task_id: str) -> VideoTaskResult:
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/tasks/{task_id}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        raw_status = data.get("output", {}).get("task_status", "")
        if raw_status == "SUCCEEDED":
            status = "succeeded"
        elif raw_status in ("FAILED", "CANCELLED", "UNKNOWN"):
            status = "failed"
        else:
            status = "running"

        video_url = data.get("output", {}).get("video_url")
        error = data.get("output", {}).get("message")

        return VideoTaskResult(
            task_id=task_id,
            status=status,
            video_url=video_url,
            last_frame_url=None,
            error=error,
        )

    async def wait_for_task(
        self,
        task_id: str,
        poll_interval: int = 15,
        max_wait: int = 600,
    ) -> VideoTaskResult:
        elapsed = 0
        while elapsed < max_wait:
            result = await self.get_task(task_id)
            if result.status in ("succeeded", "failed", "cancelled"):
                return result
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(
            f"Bailian task {task_id} did not complete within {max_wait}s"
        )


class VideoService:
    def get_provider(self, provider: str):
        if provider == "seedance":
            return SeedanceVideoService()
        elif provider == "bailian":
            return BailianVideoService()
        raise ValueError(f"Unknown video provider: {provider}")


video_service = VideoService()
