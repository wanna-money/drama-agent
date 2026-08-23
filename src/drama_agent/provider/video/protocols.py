"""Video protocol 形态(ABC)。

轻接入策略:现有 services/video_service.py 的 SeedanceVideoService /
MinimaxH3VideoService 已符合此形态(鸭子类型),
不强制继承。此 ABC 作为"video provider 实现应有的方法"的文档与类型参考。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VideoProtocol(ABC):
    provider_name: str

    @abstractmethod
    async def create_task(self, prompt: str, **kwargs) -> str: ...

    @abstractmethod
    async def get_task(self, task_id: str): ...

    @abstractmethod
    async def wait_for_task(self, task_id: str, poll_interval: int = 15, max_wait: int = 600): ...
