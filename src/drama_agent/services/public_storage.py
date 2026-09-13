"""公网可达的对象存储:声明式后端族。

**与 AssetStorage 分开是刻意的**:那一族的 url_for 回 `/api/assets/file/{key}`
—— 相对、要带 session,服务的是我们自己的前端。这一族的消费者是**外部平台**
(Ark 来取参考素材),URL 必须绝对、公网可达、无凭证。把两种语义塞进同一个
url_for,会让"这个 URL 能不能发给 Ark"变成每个调用点各自去猜。

为什么需要它:平台对**视频**参考只接受"公网 URL / asset://ID",没有 base64 那条路
(图片和音频都有)。故让视频参考可用的前提就是一个公网地址。

扩展:加一个后端 = 一个 PublicStorage 子类 + 一个工厂函数 + _BACKEND_IMPLS 登记一行(规范 5)。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# 预签名有效期的默认天数。桶保持私有、URL 到期自动失效 ——
# 比"把桶设成公共读"安全(视频是用户的创作内容)。
_DEFAULT_EXPIRES_DAYS = 7
_SECONDS_PER_DAY = 86400


class PublicStorageUnavailable(RuntimeError):
    """未配置公网存储。

    **这不是故障,是一等状态**:上层据此翻译成「视频编辑需要先配置对象存储」
    并回 409,而不是让它变成一条 500 —— 后者只会让用户看到一个与原因无关的怪错。
    """


class PublicStorage(ABC):
    @abstractmethod
    async def put(self, content: bytes, filename: str) -> str:
        """存文件,返回 storage key(后端内相对标识)。"""

    @abstractmethod
    def signed_url(self, key: str) -> str:
        """该 key 的预签名下载 URL。

        **不是 async**:签名是纯计算、不发网络请求。做成 async 会诱导调用方
        在列表渲染里 await 一圈,读代码的人也会以为每次签名都要一次往返。
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        ...


class CosPublicStorage(PublicStorage):
    """腾讯云 COS。

    SDK(`cos-python-sdk-v5`)基于 requests、**是同步的**,故 put/delete 一律
    经 asyncio.to_thread 出让事件循环:在 loop 里直接调,上传一支 1.8MB 视频期间
    worker 的心跳就停了,reap_stale 会把正在正常运行的 job 当僵尸回收。
    signed_url 例外 —— 它只做签名计算。
    """

    def __init__(self, *, bucket: str, region: str, secret_id: str,
                 secret_key: str, prefix: str = "",
                 expires_days: int = _DEFAULT_EXPIRES_DAYS) -> None:
        from qcloud_cos import CosConfig, CosS3Client  # type: ignore[import-untyped]

        self.bucket = bucket
        # 前缀让一个桶能被多个用途共用,不必各开一个桶
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self.expires = max(1, expires_days) * _SECONDS_PER_DAY
        self._client = CosS3Client(CosConfig(
            Region=region, SecretId=secret_id, SecretKey=secret_key, Scheme="https"))

    def _key_for(self, filename: str) -> str:
        # 用 uuid 而非原名:同名覆盖会让上一支片的引用静默指向新内容
        ext = Path(filename).suffix or ".bin"
        return f"{self.prefix}{uuid.uuid4()}{ext}"

    async def put(self, content: bytes, filename: str) -> str:
        key = self._key_for(filename)
        await asyncio.to_thread(
            self._client.put_object, Bucket=self.bucket, Body=content, Key=key)
        return key

    def signed_url(self, key: str) -> str:
        return self._client.get_presigned_download_url(
            Bucket=self.bucket, Key=key, Expired=self.expires)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self.bucket, Key=key)


def _make_cos(cfg: dict[str, str], secret_key: str) -> PublicStorage:
    expires_raw = cfg.get("expires_days") or ""
    return CosPublicStorage(
        bucket=cfg.get("bucket", ""),
        region=cfg.get("region", ""),
        secret_id=cfg.get("secret_id", ""),
        secret_key=secret_key,
        prefix=cfg.get("prefix", ""),
        expires_days=int(expires_raw) if str(expires_raw).isdigit()
        else _DEFAULT_EXPIRES_DAYS,
    )


# 后端 key → 工厂函数。**注册表而非 if/elif**(规范 4;工厂函数而非直存实现类,
# 与 knowledge/registry.py 同构:各后端构造签名不同,统一成 (cfg, secret_key) -> PublicStorage
# 才能让调用点不必知道具体是哪个子类)。加一个新后端 = 这里一行 + 一个工厂函数。
# TOS(火山)与 S3 兼容(MinIO/阿里 OSS)后续追加。此表也是 provider ops 词表
# (protocol_ops.py)"storage kind 支持哪些 protocol"的唯一真相 —— 那边直接
# `sorted(_BACKEND_IMPLS)`,不在此另抄一份(规范 4)。
_BACKEND_IMPLS: dict[str, Callable[[dict[str, str], str], PublicStorage]] = {
    "cos": _make_cos,
}

# 各后端的必填配置键。**声明式而非在 _storage_providers 里写 if**:
# 加一个后端时漏了这张表,那个后端的空配置就会被判为可用,而失败要等到
# 真正上传时才由 SDK 抛出 —— 那条错误不提"哪个字段没填"。此表也是
# providers.py `_validate` 保存期校验的唯一真相,不在那边另抄一份(规范 4)。
_REQUIRED_CONFIG: dict[str, tuple[str, ...]] = {
    "cos": ("bucket", "region", "secret_id"),
}

STORAGE_KIND = "storage"


def _storage_providers() -> list:
    """registry 里 protocol 属于存储族且可用(启用 + 凭证已配 + 配置完整)的声明。

    存储不像模型那样需要用户在多个之间挑,故不引入 is_default、也不引入
    "当前存储"这个新概念 —— 取第一个可用的即可。
    """
    from drama_agent import provider as provider_pkg

    out = []
    for p in provider_pkg.provider_registry.providers():
        if p.protocol not in _BACKEND_IMPLS:
            continue
        if not p.enabled or p.resolve_credential() is None:
            # 禁用或没配 SecretKey 都不算可用:否则界面会放行编辑/延长,
            # 提交时才在 COS 那层报鉴权失败
            continue
        missing = [k for k in _REQUIRED_CONFIG.get(p.protocol, ())
                   if not (p.config or {}).get(k)]
        if missing:
            # 配置不全的声明**不算可用**:算可用会让界面放行编辑/延长,
            # 而 SDK 要到真正上传时才抛,且那条错误不提是哪个字段空着。
            logger.warning("storage provider %s 配置不全,缺 %s", p.id, ", ".join(missing))
            continue
        out.append(p)
    return out


def public_storage_available() -> bool:
    """有没有可用的公网存储。供 /config/storage 下发给前端判能力(规范 4)。"""
    return bool(_storage_providers())


def get_public_storage() -> PublicStorage:
    """当前生效的公网存储;没有可用声明时抛 PublicStorageUnavailable。"""
    provs = _storage_providers()
    if not provs:
        raise PublicStorageUnavailable(
            "未配置公网对象存储。请在「存储管理」新建一条并填好 bucket 与凭证。")
    p = provs[0]
    factory = _BACKEND_IMPLS[p.protocol]
    return factory(p.config or {}, p.resolve_credential() or "")
