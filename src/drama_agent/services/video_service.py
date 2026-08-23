import asyncio
import logging
import httpx
from typing import Any
from drama_agent.config import settings
from drama_agent.services.retry import video_api_retry
from drama_agent.services.video_refs import (
    RefImage,
    RefAudio,
    cap_refs,
    reference_content_items,
    audio_content_items,
    designate_prompt,
    merge_legacy_ref,
)

logger = logging.getLogger(__name__)


class VideoTaskResult:
    def __init__(
        self,
        task_id: str,
        status: str,
        video_url: str | None = None,
        last_frame_url: str | None = None,
        error: str | None = None,
        prompt: str | None = None,
    ):
        self.task_id = task_id
        self.status = status
        self.video_url = video_url
        self.last_frame_url = last_frame_url
        self.error = error
        self.prompt = prompt


class SeedanceVideoService:
    provider_name = "seedance"
    supported_actions = ["rerun", "regenerate"]
    max_reference_images = 9
    supports_reference = True

    def __init__(self, model_id: str | None = None):
        from volcenginesdkarkruntime import AsyncArk

        self._client = AsyncArk(api_key=settings.ark_api_key)
        self.model = model_id or settings.seedance_endpoint_id or "doubao-seedance-2.0-pro"

    async def create_task(
        self,
        prompt: str,
        duration: int = 5,
        ratio: str = "16:9",
        resolution: str = "1080p",
        reference_image_url: str | None = None,
        reference_role: str | None = None,
        negative_prompt: str = "",
        references: list[RefImage] | None = None,
        audio_refs: list[RefAudio] | None = None,
    ) -> str:
        refs = merge_legacy_ref(references, reference_image_url, reference_role)
        audios = list(audio_refs or [])
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        has_subject = any(r.kind == "subject" for r in refs)
        first_frame_only = (
            len(refs) == 1 and not has_subject and refs[0].kind == "first_frame" and not audios
        )
        if first_frame_only:
            content.append(
                {"type": "image_url", "image_url": {"url": refs[0].url}, "role": "first_frame"}
            )
        elif refs or audios:
            refs = cap_refs(refs, self.max_reference_images, self.provider_name)
            content[0]["text"] = designate_prompt(prompt, refs, audios)
            content.extend(reference_content_items(refs))
            content.extend(audio_content_items(audios))

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


class MinimaxH3VideoService:
    """MiniMax H3 (video generation V2) provider, https://api.minimaxi.com."""

    provider_name = "minimax"
    supported_actions = ["rerun", "regenerate", "upscale"]
    max_reference_images = 9
    supports_reference = True

    MODEL = "MiniMax-H3"

    def __init__(self):
        self.BASE_URL = settings.minimax_video_base_url.rstrip("/")
        self._api_key = settings.minimax_video_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_content(
        self,
        prompt: str,
        references: list[RefImage] | None = None,
        audio_refs: list[RefAudio] | None = None,
    ) -> list[dict[str, Any]]:
        audios = list(audio_refs or [])
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        refs = list(references or [])
        has_subject = any(r.kind == "subject" for r in refs)
        first_frame_only = (
            len(refs) == 1 and not has_subject and refs[0].kind == "first_frame" and not audios
        )
        if first_frame_only:
            content.append(
                {"type": "image_url", "image_url": {"url": refs[0].url}, "role": "first_frame"}
            )
        elif refs or audios:
            refs = cap_refs(refs, self.max_reference_images, self.provider_name)
            content[0]["text"] = designate_prompt(prompt, refs, audios)
            content.extend(reference_content_items(refs))
            content.extend(audio_content_items(audios))
        return content

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 60,
        retryable: bool = True,
    ) -> dict[str, Any]:
        # 读类请求可安全退避重试；创建类（会产生新任务）传 retryable=False 避免重复建单。
        if retryable:
            return await self._request_retrying(
                method, path, json=json, params=params, timeout=timeout
            )
        return await self._request_once(method, path, json=json, params=params, timeout=timeout)

    @video_api_retry
    async def _request_retrying(
        self, method, path, *, json=None, params=None, timeout=60
    ) -> dict[str, Any]:
        return await self._request_once(method, path, json=json, params=params, timeout=timeout)

    async def _request_once(
        self, method, path, *, json=None, params=None, timeout=60
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method, url, headers=self._headers(), json=json, params=params
            )
            # 让 httpx 抛 HTTPStatusError，交由 retry 谓词按状态码判定是否重试。
            # 但先尽量取出 API 错误信封里的可读 message 附到异常上。
            if resp.status_code >= 400:
                message = None
                try:
                    body = resp.json()
                    if isinstance(body, dict):
                        message = (body.get("error", {}) or {}).get("message")
                except Exception:
                    pass
                resp.raise_for_status()  # 抛 httpx.HTTPStatusError（可被 retry 分类）
                # 理论到不了这里；兜底
                raise RuntimeError(message or f"MiniMax H3 request failed ({resp.status_code})")
            data = resp.json()
            if isinstance(data, dict) and data.get("type") == "error":
                err = data.get("error", {}) or {}
                raise RuntimeError(err.get("message") or "MiniMax H3 request failed")
            return data

    async def create_task(
        self,
        prompt: str,
        duration: int = 5,
        ratio: str = "16:9",
        resolution: str = "768P",
        reference_image_url: str | None = None,
        reference_role: str | None = None,
        negative_prompt: str = "",
        aigc_watermark: bool = False,
        references: list[RefImage] | None = None,
        audio_refs: list[RefAudio] | None = None,
    ) -> str:
        # H3 v2 has no dedicated negative_prompt field; ignored for signature parity.
        refs = merge_legacy_ref(references, reference_image_url, reference_role)
        body: dict[str, Any] = {
            "model": self.MODEL,
            "content": self._build_content(prompt, refs, audio_refs),
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }
        if aigc_watermark:
            body["aigc_watermark"] = True
        data = await self._request("POST", "/v2/video_generation", json=body, retryable=False)
        return data["task_id"]

    async def get_task(self, task_id: str) -> VideoTaskResult:
        data = await self._request("GET", f"/v2/query/video_generation/{task_id}")
        task = data.get("task", {})
        content = task.get("content") or {}
        error = task.get("error")
        if error and not isinstance(error, str):
            error = error.get("message") or str(error)
        return VideoTaskResult(
            task_id=task.get("id", task_id),
            status=task.get("status", "unknown"),
            video_url=content.get("url"),
            last_frame_url=None,
            error=error,
            prompt=content.get("prompt"),
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
            f"MiniMax H3 task {task_id} did not complete within {max_wait}s"
        )

    async def list_tasks(
        self,
        page_num: int = 1,
        page_size: int = 20,
        status: str | None = None,
        task_ids: list[str] | None = None,
        model: str | None = None,
        task_type: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_num": page_num, "page_size": page_size}
        if status:
            params["filter.status"] = status
        if task_ids:
            params["filter.task_ids"] = task_ids
        if model:
            params["filter.model"] = model
        if task_type:
            params["filter.task_type"] = task_type
        return await self._request("GET", "/v2/query/video_generation", params=params)

    async def delete_task(self, task_id: str) -> dict[str, Any]:
        return await self._request("DELETE", f"/v2/video_generation/{task_id}")

    async def create_context_ir(
        self,
        prompt: str,
        duration: int = 5,
        ratio: str = "16:9",
        reference_image_url: str | None = None,
        reference_role: str | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self.MODEL,
            "content": self._build_content(
                prompt, merge_legacy_ref(None, reference_image_url, reference_role)
            ),
            "duration": duration,
            "ratio": ratio,
        }
        data = await self._request("POST", "/v2/h3_context_ir", json=body, retryable=False)
        return data["task_id"]

    async def create_regeneration(
        self,
        source_task_id: str | None = None,
        base_video_url: str | None = None,
        resolution: str = "2K",
        aigc_watermark: bool = False,
    ) -> str:
        if bool(source_task_id) == bool(base_video_url):
            raise ValueError(
                "create_regeneration requires exactly one of source_task_id or base_video_url"
            )
        body: dict[str, Any] = {"model": self.MODEL, "resolution": resolution}
        if source_task_id:
            body["source_task_id"] = source_task_id
        else:
            body["content"] = [
                {"type": "video_url", "video_url": {"url": base_video_url}, "role": "base_video"}
            ]
        if aigc_watermark:
            body["aigc_watermark"] = True
        data = await self._request("POST", "/v2/video_regeneration", json=body, retryable=False)
        return data["task_id"]


class VideoService:
    def get_provider(self, provider: str):
        if provider == "seedance":
            return SeedanceVideoService()
        elif provider == "seedance-2.5":
            return SeedanceVideoService(
                model_id=settings.seedance_2_5_endpoint_id or "doubao-seedance-2.5-pro"
            )
        elif provider == "minimax":
            return MinimaxH3VideoService()
        raise ValueError(f"Unknown video provider: {provider}")


video_service = VideoService()
