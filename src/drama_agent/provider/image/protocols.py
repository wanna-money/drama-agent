"""Image protocol 抽象 + 具体实现(Ark Seedream / OpenAI)。返回统一拉平为 bytes。

协议级差异 → 不同 Protocol 类;注册表按 key 分发,与 llm/protocols.py 同模式。
"""
from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from drama_agent.provider.base import Model, Provider
from drama_agent.services.retry import llm_retry


class ImageResult(BaseModel):
    images: list[bytes]                     # 生成/编辑出的图片字节(可多张)
    usage: dict[str, int] | None = None


class ImageProtocol(ABC):
    @abstractmethod
    async def generate(
        self, provider: Provider, model: Model, prompt: str, *, size: str | None, n: int
    ) -> ImageResult:
        ...

    @abstractmethod
    async def edit(
        self, provider: Provider, model: Model, image: bytes, prompt: str, *,
        mask: bytes | None, size: str | None, n: int,
    ) -> ImageResult:
        ...

    async def _download(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content

    async def _to_bytes(self, resp) -> list[bytes]:
        """把 SDK 返回项(b64_json 或 url)统一拉平为 bytes。"""
        out: list[bytes] = []
        for item in (getattr(resp, "data", None) or []):
            b64 = getattr(item, "b64_json", None)
            if b64:
                out.append(base64.b64decode(b64))
            elif getattr(item, "url", None):
                out.append(await self._download(item.url))
        return out


class DoubaoImageProtocol(ImageProtocol):
    """火山方舟 Ark(Seedream)。复用 volcenginesdkarkruntime.AsyncArk(与 seedance 同 SDK/key)。
    Ark SDK 只有 images.generate;edit 暂不支持 → 抛 NotImplementedError。"""

    def _client(self, provider: Provider):
        from volcenginesdkarkruntime import AsyncArk
        return AsyncArk(api_key=provider.resolve_credential() or "placeholder")

    @llm_retry
    async def _generate(self, client, **kwargs):
        return await client.images.generate(**kwargs)

    async def generate(self, provider, model, prompt, *, size, n):
        client = self._client(provider)
        # Ark(Seedream)images.generate 无 n 参数、单次出 1 图;循环 n 次以兑现协议"返回 n 张"契约。
        kwargs: dict = {"model": model.id, "prompt": prompt, "response_format": "b64_json"}
        if size:
            kwargs["size"] = size
        resps = await asyncio.gather(*[self._generate(client, **kwargs) for _ in range(n)])
        images: list[bytes] = []
        for resp in resps:
            images += await self._to_bytes(resp)
        return ImageResult(images=images)

    async def edit(self, provider, model, image, prompt, *, mask, size, n):
        raise NotImplementedError("Seedream(Ark)暂不支持图片编辑")


class OpenAIImageProtocol(ImageProtocol):
    """OpenAI images.generate / images.edit(gpt-image-2)。"""

    def _client(self, provider: Provider):
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            api_key=provider.resolve_credential() or "placeholder",
            base_url=provider.base_url or None,
        )

    @llm_retry
    async def _generate(self, client, **kwargs):
        return await client.images.generate(**kwargs)

    @llm_retry
    async def _edit(self, client, **kwargs):
        return await client.images.edit(**kwargs)

    async def generate(self, provider, model, prompt, *, size, n):
        client = self._client(provider)
        kwargs: dict = {"model": model.id, "prompt": prompt, "n": n}
        if size:
            kwargs["size"] = size
        resp = await self._generate(client, **kwargs)
        return ImageResult(images=await self._to_bytes(resp))

    async def edit(self, provider, model, image, prompt, *, mask, size, n):
        client = self._client(provider)
        kwargs: dict = {"model": model.id, "image": image, "prompt": prompt, "n": n}
        if mask:
            kwargs["mask"] = mask
        if size:
            kwargs["size"] = size
        resp = await self._edit(client, **kwargs)
        return ImageResult(images=await self._to_bytes(resp))


# protocol key → 单例。新增协议在此登记(扩展点)。
_IMAGE_PROTOCOLS: dict[str, ImageProtocol] = {
    "doubao-image": DoubaoImageProtocol(),
    "openai-image": OpenAIImageProtocol(),
}


def get_image_protocol(key: str) -> ImageProtocol:
    proto = _IMAGE_PROTOCOLS.get(key)
    if proto is None:
        raise ValueError(f"Unknown image protocol: {key!r}")
    return proto
