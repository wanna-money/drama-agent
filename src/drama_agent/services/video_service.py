import asyncio
import logging
import httpx
from typing import Any
from drama_agent.config import settings
from drama_agent.db.enums import ClipTaskType
from drama_agent.provider.base import ResponseShape, dig
from drama_agent.services.retry import video_api_retry
from drama_agent.services.video_refs import (
    RefImage,
    RefAudio,
    RefVideo,
    append_negative,
    cap_refs,
    cap_video_refs,
    reference_content_items,
    video_content_items,
    audio_content_items,
    designate_prompt,
    merge_legacy_ref,
)

logger = logging.getLogger(__name__)


def _as_str(v: object) -> str | None:
    """按声明路径取出的值是 object;空字符串按"没有"处理(网关常回空串而非省略字段)。"""
    return str(v) if v not in (None, "") else None


def _as_int(v: object) -> int | None:
    """按声明路径取出的值是 object;非数字按"没有"处理(网关可能回空串)。"""
    if isinstance(v, int):
        return v
    if isinstance(v, str) and (v.lstrip("-").isdigit()):
        return int(v)
    return None


class VideoTaskResult:
    """一次生成任务的结果。

    seed / revised_prompt 是**平台回传的实际取值**:不传 seed 时模型自己抽一个并在响应里
    告知,把它落库后「重跑」才能真正重跑(否则每次都是另一支视频)。revised_prompt 是模型
    实际使用的 prompt,与我们送出的可能不同 —— 排查"为什么长这样"要看它。
    provider 不回传这两项时为 None。

    duration 是平台回传的**实际**时长(整数秒,由帧数/24 向下取整)。提交 -1 时
    只有它能给出真实秒数 —— 记账要用它,落 -1 会算成负数秒。
    """

    def __init__(
        self,
        task_id: str,
        status: str,
        video_url: str | None = None,
        last_frame_url: str | None = None,
        error: str | None = None,
        prompt: str | None = None,
        seed: int | None = None,
        revised_prompt: str | None = None,
        duration: int | None = None,
    ):
        self.task_id = task_id
        self.status = status
        self.video_url = video_url
        self.last_frame_url = last_frame_url
        self.error = error
        self.prompt = prompt
        self.seed = seed
        self.revised_prompt = revised_prompt
        self.duration = duration


class SeedanceVideoService:
    provider_name = "seedance"
    supported_actions = ["rerun", "regenerate"]
    # 类级默认:未从 model 注入声明时的兜底(Ark 全模态参考的平台上限)
    max_reference_images = 9
    # 类级默认:2.0 不强制;2.5 经 Model 声明注入 True(见 provider/base.Model)
    forces_adaptive_ratio = False
    supports_reference = True
    supports_seed = True          # Ark 接受 seed 入参,并在任务响应里回传实际取值
    # 类级默认:未从 model 注入声明时的兜底(2.0 系列的平台上限)
    max_reference_videos = 3
    # 类级默认:2.0 不认 omni_reference_task_type;2.5 经 Model 声明注入 True
    supports_omni_task_type = False
    # 类级默认:"没有自定义接入声明"是该类的静态默认语义(一律走 SDK 官方路径)。
    paths: dict[str, str] = {}
    response_map: dict[str, str] = {}

    # Ark 官方响应的字段位置;provider 未声明 response_map 时按此解析。
    ARK_FIELDS = {
        "task_id": "id", "status": "status",
        "video_url": "content.video_url", "last_frame_url": "content.last_frame_url",
        "error": "error", "seed": "seed", "revised_prompt": "revised_prompt",
        "duration": "duration",
    }

    @property
    def _shape(self) -> ResponseShape:
        return ResponseShape(self.response_map, self.ARK_FIELDS)

    def _require_api_key(self) -> None:
        """发请求前确认凭证已配;缺失时给出可行动的原因。

        **不放 __init__**:构造实例还有一条纯读能力声明的路径(video_actions 读
        supported_actions/resolutions 判断产物能做哪些动作,不碰网络),在构造时抛
        会让那条路径整个不可用。

        用 getattr 取而非直接读属性:部分测试用 `__new__` 绕过 __init__ 只手设需要的
        属性,直接读会抛 AttributeError —— 那与"没配 key"是两件事,会掩盖真正的原因。
        """
        if not getattr(self, "_api_key", ""):
            raise ValueError(
                f"{self.provider_name} 未配置 API key,请在「模型管理」为该 provider 填写")

    def __init__(self, model_id: str | None = None,
                 api_key: str | None = None, base_url: str | None = None,
                 paths: dict[str, str] | None = None,
                 response_map: dict[str, str] | None = None,
                 max_reference_images: int | None = None,
                 forces_adaptive_ratio: bool | None = None,
                 max_reference_videos: int | None = None,
                 supports_omni_task_type: bool | None = None):
        from volcenginesdkarkruntime import AsyncArk

        # 凭证优先来自**注册表里那条 provider**(api_key/base_url 由调用方解析后传入),
        # settings 只作兜底。写死 settings.ark_api_key 时,用户在「模型管理」为某个
        # provider 配的 key 与 base_url 一律不生效。
        self._api_key = api_key or settings.ark_api_key
        self._base_url = (base_url or "").rstrip("/")
        # 自定义接入路径/响应映射:同一 Ark 协议被不同网关代理时路径与响应包装各异,
        # 而请求体一致。留空则整条路径走 SDK(行为零变化);声明了才走 HTTP 直调。
        # 判据是"有没有声明这个功能键",不是"是不是某一家网关"。
        self.paths = dict(paths or {})
        self.response_map = dict(response_map or {})
        # 上限的权威是 model 声明(见 provider/base.Model);未声明(0/None)时留用类级默认。
        # 实例属性遮蔽类属性,故这里赋值即生效,create_task 的 cap_refs 无需改动。
        if max_reference_images:
            self.max_reference_images = max_reference_images
        if forces_adaptive_ratio is not None:
            self.forces_adaptive_ratio = forces_adaptive_ratio
        if max_reference_videos is not None:
            self.max_reference_videos = max_reference_videos
        if supports_omni_task_type is not None:
            self.supports_omni_task_type = supports_omni_task_type
        kwargs: dict = {"api_key": self._api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncArk(**kwargs)
        self.model = model_id or settings.seedance_endpoint_id or "doubao-seedance-2.0-pro"

    async def _http(self, method: str, path: str, *, json: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._api_key}",
                   "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await (client.post(url, json=json, headers=headers) if method == "POST"
                          else client.get(url, headers=headers))
            body = resp.json() if resp.content else {}
            resp.raise_for_status()   # 抛 HTTPStatusError,交 retry 谓词按状态码分类
        return body if isinstance(body, dict) else {}

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
        seed: int | None = None,
        video_refs: list[RefVideo] | None = None,
        task_type: str = "",
    ) -> str:
        # 凭证在**发请求前**校验,不在 __init__ —— 构造实例还有一条纯读能力声明的路径
        # (video_actions 用它读 supported_actions/resolutions,不碰网络),
        # 在构造时抛会让"这个产物能做哪些动作"整个不可用。
        # 这里早失败是为了盖掉 SDK 对空 key 报的 "Connection error." ——
        # 那条错误与真正的网络故障无法区分,且要等整条流水线跑完才暴露。
        self._require_api_key()
        refs = merge_legacy_ref(references, reference_image_url, reference_role)
        audios = list(audio_refs or [])
        # Ark 没有独立的 negative_prompt 字段 —— 折进 prompt 文本。收下参数却不用等于
        # 用户在界面上改了负向提示、实际请求毫无变化(比不给这个输入框更糟)。
        prompt = append_negative(prompt, negative_prompt)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        videos = cap_video_refs(
            list(video_refs or []), self.max_reference_videos, self.provider_name)
        has_subject = any(r.kind == "subject" for r in refs)
        # 原生首帧模式的前提是"只有一张首帧图、别无他物" —— 有视频参考时
        # 必须走全模态参考,否则那支视频根本不进请求体
        first_frame_only = (
            len(refs) == 1 and not has_subject and refs[0].kind == "first_frame"
            and not audios and not videos
        )
        if first_frame_only:
            content.append(
                {"type": "image_url", "image_url": {"url": refs[0].url}, "role": "first_frame"}
            )
        elif refs or audios or videos:
            refs = cap_refs(refs, self.max_reference_images, self.provider_name)
            content[0]["text"] = designate_prompt(prompt, refs, audios, videos)
            content.extend(reference_content_items(refs))
            content.extend(video_content_items(videos))
            content.extend(audio_content_items(audios))

        # 有首帧/尾帧时,部分模型强制 adaptive 比例(平台按首帧图自动定比例)——
        # 传具体比例会被拒,而报错指向"参数与任务类型不兼容",与"我明明传了 9:16"对不上。
        # 判据来自 Model 声明,不按模型名判:见 provider/base.Model.forces_adaptive_ratio。
        # 只在**真有首/尾帧**时改:一刀切会让文生视频丢掉竖屏。
        if self.forces_adaptive_ratio and any(
                r.kind in ("first_frame", "last_frame") for r in refs):
            ratio = "adaptive"

        extra: dict[str, Any] = {}
        # 显式声明子任务类型,让平台在**提交时**就校验该类型的特殊限制,
        # 而不是任务跑起来之后异步报错(那时错误只说"参数不兼容")。
        # 未声明支持的模型不发这个字段 —— 发它不认的参数。
        if self.supports_omni_task_type and task_type:
            extra["omni_reference_task_type"] = task_type
            if task_type in (ClipTaskType.EDIT.value, ClipTaskType.EXTEND.value):
                # 输出比例由原视频决定,传具体比例会被拒
                ratio = "adaptive"
            if task_type == ClipTaskType.EDIT.value:
                # 输出时长与待编辑视频一致,平台只收 -1(真实秒数在查询响应里回传)
                duration = -1
        if seed is not None:
            extra["seed"] = seed
        payload: dict[str, Any] = {
            "model": self.model, "content": content, "duration": duration,
            "resolution": resolution, "ratio": ratio, "return_last_frame": True, **extra,
        }
        submit_path = self.paths.get("video_submit")
        if submit_path:
            body = await self._http("POST", submit_path, json=payload)
            tid = self._shape.get(body, "task_id")
            if not tid:
                # 该网关把错误放在 body 里(HTTP 仍可能是 200)。返回 None 会一路流到轮询,
                # 表现成"任务不存在"的假象,真实原因被吞掉。
                msg = dig(body, "error.message") or dig(body, "message") or str(body)[:200]
                raise RuntimeError(f"视频任务提交失败: {msg}")  # noqa: TRY003
            return str(tid)
        create_result = await self._client.content_generation.tasks.create(**payload)
        return create_result.id

    async def get_task(self, task_id: str) -> VideoTaskResult:
        query_path = self.paths.get("video_query")
        if query_path:
            body = await self._http("GET", query_path.replace("{task_id}", task_id))
            raw_error = self._shape.get(body, "error")
            if raw_error is not None and not isinstance(raw_error, str):
                # 部分网关在成功时也回一个 error 对象(code=0、message 为空)。
                # 不单独取 message 判空,每支成片都会被判成失败。
                raw_error = dig(body, "error.message")
            seed = self._shape.get(body, "seed")
            return VideoTaskResult(
                task_id=str(self._shape.get(body, "task_id") or task_id),
                status=self._shape.status(str(self._shape.get(body, "status") or "unknown")),
                video_url=_as_str(self._shape.get(body, "video_url")),
                last_frame_url=_as_str(self._shape.get(body, "last_frame_url")),
                error=_as_str(raw_error),
                seed=int(seed) if isinstance(seed, (int, str)) and str(seed).isdigit() else None,
                revised_prompt=_as_str(self._shape.get(body, "revised_prompt")),
                duration=_as_int(self._shape.get(body, "duration")),
            )
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
            # 未传 seed 时模型自抽一个,响应里带回来 —— 落库后「重跑」才是真重跑
            seed=getattr(task, "seed", None),
            revised_prompt=getattr(task, "revised_prompt", None),
            duration=getattr(task, "duration", None),
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
    # 类级默认:未从 model 注入声明时的兜底
    max_reference_images = 9
    supports_reference = True
    # H3 v2 没有 seed 字段:传了也无处可放,故不声明支持 —— 这条集上的「重跑」只能是"再抽一次"
    supports_seed = False
    # 类级默认:未声明自定义接入时走官方路径(与 SeedanceVideoService 同理)
    paths: dict[str, str] = {}
    response_map: dict[str, str] = {}

    MODEL = "MiniMax-H3"

    # H3 官方响应的字段位置;provider 未声明 response_map 时按此解析。
    H3_FIELDS = {"task_id": "task_id"}

    @property
    def _shape(self) -> ResponseShape:
        return ResponseShape(self.response_map, self.H3_FIELDS)

    # 类级默认:H3 不强制 adaptive(与 Seedance 2.0 同)
    forces_adaptive_ratio = False
    # H3 v2 没有视频参考,也不认 omni_reference_task_type
    max_reference_videos = 0
    supports_omni_task_type = False

    def __init__(self, model_id: str | None = None,
                 api_key: str | None = None, base_url: str | None = None,
                 paths: dict[str, str] | None = None,
                 response_map: dict[str, str] | None = None,
                 max_reference_images: int | None = None,
                 forces_adaptive_ratio: bool | None = None,
                 max_reference_videos: int | None = None,
                 supports_omni_task_type: bool | None = None):
        """构造签名与 SeedanceVideoService 一致 —— 工厂用同一套 kwargs 实例化任何
        protocol(见 _PROTOCOL_IMPLS)。签名分叉会让工厂被迫按 protocol 挑参数。"""
        self.BASE_URL = (base_url or settings.minimax_video_base_url).rstrip("/")
        self._api_key = api_key or settings.minimax_video_api_key
        # 模型 id 的权威是 Model 声明,不是类常量 —— 用户在「模型管理」换了模型名要生效。
        if model_id:
            self.MODEL = model_id
        # 与 seedance 同源的接入声明:留空走官方路径(行为零变化),声明了按声明发。
        self.paths = dict(paths or {})
        self.response_map = dict(response_map or {})
        # 上限的权威是 model 声明(见 provider/base.Model);未声明(0/None)时留用类级默认。
        # 实例属性遮蔽类属性,故这里赋值即生效,create_task 的 cap_refs 无需改动。
        if max_reference_images:
            self.max_reference_images = max_reference_images
        if forces_adaptive_ratio is not None:
            self.forces_adaptive_ratio = forces_adaptive_ratio
        if max_reference_videos is not None:
            self.max_reference_videos = max_reference_videos
        if supports_omni_task_type is not None:
            self.supports_omni_task_type = supports_omni_task_type

    def _path(self, op: str, default: str, **fmt) -> str:
        """该操作的实际路径:provider 声明优先,否则官方默认。{task_id} 等占位符就地替换。"""
        tpl = self.paths.get(op) or default
        for k, v in fmt.items():
            tpl = tpl.replace("{" + k + "}", str(v))
        return tpl

    def _require_api_key(self) -> None:
        """发请求前确认凭证已配;与 SeedanceVideoService 同理(见那边的 docstring)。"""
        if not self._api_key:
            raise ValueError(
                f"{self.provider_name} 未配置 API key,请在「模型管理」为该 provider 填写")

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
        seed: int | None = None,
        video_refs: list[RefVideo] | None = None,
        task_type: str = "",
    ) -> str:
        # 凭证在发请求前校验,不在 __init__(理由见 _require_api_key 的 docstring)
        self._require_api_key()
        # H3 v2 既无 negative_prompt 也无 seed 字段:负向提示折进 prompt 文本(收下不用
        # 等于用户改了没效果);seed 无处可放,只能忽略(见 supports_seed=False)。
        if video_refs:
            # 收下却不发等于用户以为传了参考视频、实际请求里没有它。
            # 上限的权威是 Model 声明(这里是 0),接口层已按它拦过一道;
            # 这条是实现层的兜底 —— 两处都拦是因为直接调 service 的路径不过接口。
            raise ValueError(
                f"{self.provider_name} 不支持参考视频(max_reference_videos=0)")
        refs = merge_legacy_ref(references, reference_image_url, reference_role)
        prompt = append_negative(prompt, negative_prompt)
        body: dict[str, Any] = {
            "model": self.MODEL,
            "content": self._build_content(prompt, refs, audio_refs),
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }
        if aigc_watermark:
            body["aigc_watermark"] = True
        data = await self._request(
            "POST", self._path("video_submit", "/v2/video_generation"),
            json=body, retryable=False)
        tid = self._shape.get(data, "task_id")
        if not tid:
            msg = dig(data, "base_resp.status_msg") or str(data)[:200]
            raise RuntimeError(f"视频任务提交失败: {msg}")
        return str(tid)

    async def get_task(self, task_id: str) -> VideoTaskResult:
        data = await self._request(
            "GET", self._path("video_query", "/v2/query/video_generation/{task_id}",
                              task_id=task_id))
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
    def get_provider(self, provider: str, model: str | None = None):
        """按 protocol 取 provider 实现,并把**注册表里那条 provider 的凭证 + 接入声明**注入。

        model 是 registry 的**模型引用**(可带 "provider/" 前缀寻址),不等于上游认的模型名
        —— 解析后一律用 Model.id 发出去。与 LLM 侧同一条路径(llm_service 也是
        resolve_model 拿 (prov, mdl) 再把 mdl 交给 protocol)。
        解析不到时退回 settings 兜底 + 原样当模型名,保证老调用点(裸 endpoint id、
        只有 provider 名的产物动作)仍可用。
        """
        impl = _PROTOCOL_IMPLS.get(provider)
        if impl is None:
            raise ValueError(
                f"Unknown video provider: {provider}. "
                f"已注册的 protocol: {sorted(_PROTOCOL_IMPLS)}")
        resolved = self._resolve(model)
        return impl(model_id=resolved["model_id"] or None, **resolved["creds"])

    @staticmethod
    def _resolve(model: str | None) -> dict:
        """把模型引用解析成 {上游模型名, 该 provider 的凭证与接入声明}。

        paths/response_map 必须随凭证一起下来:界面上配好的自定义路径若不传进实现,
        真正调用时仍走官方默认,表现为"配了没用"。
        """
        if not model:
            return {"model_id": None, "creds": {}}
        try:
            from drama_agent import provider as provider_pkg
            prov, mdl = provider_pkg.provider_registry.resolve_model(model)
        except Exception as e:  # noqa: BLE001 — 解析不到不阻断,退回 settings 兜底
            logger.warning("video provider 解析失败,退回 settings: model=%s err=%s", model, e)
            return {"model_id": model, "creds": {}}
        return {
            "model_id": mdl.id,
            "creds": {"api_key": prov.resolve_credential(), "base_url": prov.base_url,
                      "paths": prov.paths, "response_map": prov.response_map,
                      "max_reference_images": mdl.max_reference_images,
                      "forces_adaptive_ratio": mdl.forces_adaptive_ratio,
                      "max_reference_videos": mdl.max_reference_videos,
                      "supports_omni_task_type": mdl.supports_omni_task_type},
        }


# protocol → 实现类。**注册表而非 if/elif**(规范 4):加一个新 protocol =
# 这里加一行 + 一个实现类。**不要按模型版本加条目** —— 同一协议下的版本差异
# (取值范围、构造约束)属于 Model 声明,见 provider/base.Model。
_PROTOCOL_IMPLS: dict[str, type] = {
    "seedance": SeedanceVideoService,
    "minimax": MinimaxH3VideoService,
}


video_service = VideoService()
