"""散片(直接生成)端点。

散片与 Episode 平级(都挂 project_id),不属于任何集。写接口带状态守卫 + 幂等(规范 3)。
设计见 docs/superpowers/specs/2026-09-07-simple-mode-clip-generation-design.md
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent import provider as provider_pkg
from drama_agent.db.enums import ClipTaskType, JobKind
from drama_agent.db.models import Job, Project, VideoArtifact
from drama_agent.db.session import get_db
from drama_agent.services import clip_service, job_service
from drama_agent.services.public_storage import get_public_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["clips"])

# 参考图语义(与 services/video_refs.RefKind 同源)。自由字符串会被下游当作主体参考,
# 用户以为设了首帧、实际没有 —— 故在接口层就收敛为枚举。
_REF_KINDS = frozenset({"first_frame", "last_frame", "subject"})
# 未能解析出模型声明时的兜底上限(两个内置 provider 的平台上限均为 9)
_FALLBACK_MAX_REFS = 9


class RefImageIn(BaseModel):
    url: str
    kind: str
    subject_name: str | None = None
    view: str | None = None


class RefAudioIn(BaseModel):
    url: str
    subject_name: str | None = None


class RefVideoIn(BaseModel):
    """参考视频。url 装的是**公网存储的 storage key**(或已是公网 URL)。

    不收 data URI —— 平台对视频只接受公网 URL / asset://ID。
    """

    url: str
    subject_name: str | None = None
    # 该支视频的时长(秒)。**用于总时长求和校验** —— 平台对"所有参考视频之和"
    # 有上限(2.5 是 30s、2.0 是 15s),超了会异步报错。上传端点会回 duration,
    # 前端原样带回来;拿不到(未装 ffprobe)时为 None,那一支不计入求和。
    duration: int | None = None


class CreateClipRequest(BaseModel):
    """一次「直接生成」请求。prompt 是用户手写的、实际发给视频模型的文本。"""
    prompt: str
    negative_prompt: str | None = None
    duration: int = 5
    resolution: str = ""
    aspect_ratio: str = ""
    video_provider: str = ""
    video_model: str = ""
    references: list[RefImageIn] = []
    audio_refs: list[RefAudioIn] = []
    task_type: str = ClipTaskType.REFERENCE.value
    video_refs: list[RefVideoIn] = []


async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    p = (await db.execute(
        select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(status_code=404, detail="作品不存在")
    return p


def _resolved_model(model_ref: str):
    """按模型引用解析出 Model 声明;解析不到返回 None(不阻断创建)。"""
    if not model_ref:
        return None
    try:
        _, mdl = provider_pkg.provider_registry.resolve_model(model_ref)
    except Exception:  # noqa: BLE001 — 解析不到不阻断创建
        return None
    return mdl


def _max_refs(model_ref: str) -> int:
    """该模型的参考图上限。权威在 Model 声明(规范 4);解析不到时用平台兜底。

    按 model id 解析、不传 provider_hint:registry 的 `_models` 表对同名 id 是后者覆盖
    前者,故同名 id 只有一条可解析;而 `video_service.get_provider` → `_resolve` 读的是
    **同一张表**,上限与真正发请求的那个实现不会分叉。
    **不要把 `video_provider` 当 provider_hint 传进来** —— 那个字段装的是 protocol
    (如 `"seedance"`)而非 provider id(`"seedance-video"`),传了会
    `ValueError: Unknown provider` 从而每次都退到兜底上限。要按 provider 消歧,
    须让接口层同时下发 provider id。
    """
    mdl = _resolved_model(model_ref)
    return (mdl.max_reference_images if mdl else 0) or _FALLBACK_MAX_REFS


def _check_duration(model_ref: str, duration: int, task_type: str) -> None:
    """时长必须落在该模型声明的闭区间内;**声明支持子任务类型**的模型上编辑任务只收 -1。

    区间随模型不同(Seedance 2.0 / MiniMax H3 是 4-15,Seedance 2.5 是 4-30)。
    前端会把越界值夹回区间,但那只是体验 —— 规则的权威在后端(规范 4)。

    **按区间判,不要退回成枚举清单**:平台收的是区间,用清单会主动拒掉它其实
    接受的值(如 7 秒),而那种 422 比不校验更误导。未声明区间(0)时不校验。

    `-1` 的准入判据是 **Model.supports_omni_task_type**,不是 task_type ——
    必须与 create_task 构造 payload 时用的那一位一致。只看 task_type 会拒掉
    "2.0 + 编辑 + 具体秒数"这个合法组合(2.0 不认 omni 参数、平台按提示词 auto 推断,
    故它的编辑任务本就该给具体时长)。
    """
    mdl = _resolved_model(model_ref)
    declares_task_type = bool(mdl and mdl.supports_omni_task_type)
    if declares_task_type and task_type == ClipTaskType.EDIT.value:
        if duration != -1:
            raise HTTPException(
                status_code=422,
                detail="该模型的视频编辑时长与原视频一致,只能提交 -1")
        return
    if duration == -1:
        # 不声明子任务类型的模型上,-1 会让平台自选时长,而界面上用户明确选过秒数
        raise HTTPException(
            status_code=422, detail="只有支持子任务类型的模型的视频编辑允许时长为 -1")
    mdl_ok = mdl and mdl.min_duration and mdl.max_duration
    if not mdl_ok:
        return
    if not mdl.min_duration <= duration <= mdl.max_duration:
        raise HTTPException(
            status_code=422,
            detail=f"该模型支持 {mdl.min_duration}-{mdl.max_duration} 秒,当前 {duration} 秒")


def _check_task_type(task_type: str) -> str:
    """任务类型必须是枚举成员(规范 1)。

    自由字符串会被原样发给平台,而它按提示词自行判定 —— 判成别的类型时
    触发异步报错,错误信息指向参数不兼容,与"我选了延长"对不上。
    """
    try:
        return ClipTaskType(task_type).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"任务类型非法: {task_type!r};须是 "
                   f"{[t.value for t in ClipTaskType]} 之一") from None


def _check_video_refs(model_ref: str, task_type: str, videos: list) -> None:
    """参考视频的数量上限与任务前置。

    上限的权威是 Model 声明(规范 4);0 表示该模型没有视频参考。
    编辑/延长必须至少有一支参考视频 —— 平台要求 content 含 reference_video,
    空着提交必被拒,在这里拒掉比让它跑起来再异步报错好。
    """
    mdl = _resolved_model(model_ref)
    cap = mdl.max_reference_videos if mdl else 0
    if videos and cap <= 0:
        raise HTTPException(
            status_code=422,
            detail="该模型不支持参考视频,无法做视频编辑或延长")
    if len(videos) > cap:
        raise HTTPException(
            status_code=422,
            detail=f"参考视频最多 {cap} 个,当前 {len(videos)} 个")
    if task_type in (ClipTaskType.EDIT.value, ClipTaskType.EXTEND.value) and not videos:
        raise HTTPException(
            status_code=422, detail="视频编辑与延长需要至少一支参考视频")
    # 总时长上限恰好等于该模型的单支上限(手册:2.5 是 30s/10 个、2.0 是 15s/3 个),
    # 故复用 max_duration,不另立一个声明字段。
    # duration 为 None 的(未装 ffprobe 时上传端点回不出来)不计入 —— 宁可漏判,
    # 也不要因为拿不到时长就拒掉一次合法提交。
    total = sum(v.duration for v in videos if v.duration)
    cap_seconds = (mdl.max_duration if mdl else 0) or 0
    if cap_seconds and total > cap_seconds:
        raise HTTPException(
            status_code=422,
            detail=f"参考视频总时长最多 {cap_seconds} 秒,当前 {total} 秒")


async def _get_clip_or_404(db: AsyncSession, project_id: str, clip_id: str) -> dict:
    """取散片并校验归属。**归属校验只住在这里** —— 只按 clip_id 查会让 A 作品读到
    B 作品的散片,而把同一个判断抄在每个端点里,就得靠人维护"三处保持一致"。
    """
    clip = await clip_service.get(db, clip_id)
    if clip is None or clip["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="散片不存在")
    return clip


@router.post("/{project_id}/clips")
async def create_clip(
    project_id: str, req: CreateClipRequest, db: AsyncSession = Depends(get_db)
):
    """建一条散片请求并入队。

    先建 clip 行(flush)再 enqueue —— enqueue 内部的 commit 会把两者一并落库(单事务)。
    反过来写就是两个事务,中间崩溃会留下"队列里有 job、clips 表里没那一行"的错位。
    """
    await _get_project_or_404(db, project_id)
    if not req.prompt.strip():
        raise HTTPException(status_code=422, detail="提示词不能为空")
    bad = [r.kind for r in req.references if r.kind not in _REF_KINDS]
    if bad:
        raise HTTPException(
            status_code=422, detail=f"参考图类型非法: {bad};须是 {sorted(_REF_KINDS)} 之一")
    cap = _max_refs(req.video_model)
    if len(req.references) > cap:
        raise HTTPException(
            status_code=422, detail=f"参考图最多 {cap} 张,当前 {len(req.references)} 张")
    task_type = _check_task_type(req.task_type)
    _check_video_refs(req.video_model, task_type, req.video_refs)
    _check_duration(req.video_model, req.duration, task_type)

    clip = await clip_service.create(
        db, project_id=project_id, prompt=req.prompt.strip(),
        negative_prompt=(req.negative_prompt or "").strip() or None,
        duration=req.duration, resolution=req.resolution,
        aspect_ratio=req.aspect_ratio, video_provider=req.video_provider,
        video_model=req.video_model,
        references=[r.model_dump() for r in req.references] or None,
        audio_refs=[a.model_dump() for a in req.audio_refs] or None,
        video_refs=[v.model_dump() for v in req.video_refs] or None,
        task_type=task_type,
    )
    # dedup_key = clip.id:每次提交是一个**新** clip,天然不会重复;
    # 同一个 clip 的 job 重复入队才会命中既有行(幂等)。
    # max_attempts=1:失败多为内容审核/参数问题,重试只是重复付费 ——
    # 让用户看到原因后自己改 prompt 重提。
    job = await job_service.enqueue(
        db, JobKind.CLIP, clip["id"], dedup_key=clip["id"],
        project_id=project_id, max_attempts=1,
    )
    return {"clip": clip, "job_id": job["id"]}


@router.get("/{project_id}/clips")
async def list_clips(project_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    return {"clips": await clip_service.list_by_project(db, project_id)}


@router.get("/{project_id}/clips/{clip_id}")
async def get_clip(project_id: str, clip_id: str, db: AsyncSession = Depends(get_db)):
    return {"clip": await _get_clip_or_404(db, project_id, clip_id)}


@router.delete("/{project_id}/clips/{clip_id}")
async def delete_clip(project_id: str, clip_id: str, db: AsyncSession = Depends(get_db)):
    """删散片,并连带清掉它的 job 行与根产物。

    这两样都以 clip_id 为归属键(job 的 `episode_id` 列载 clip_id、产物的 `shot_id`
    载 clip_id),散片一删就再没有任何入口能引用到它们 —— 不清就是永久孤儿。
    """
    clip = await _get_clip_or_404(db, project_id, clip_id)
    await db.execute(delete(Job).where(
        Job.episode_id == clip_id, Job.kind == JobKind.CLIP.value))
    await db.execute(delete(VideoArtifact).where(VideoArtifact.shot_id == clip_id))
    # 公网副本也要清:它以 clip 的 storage_key 为唯一引用,散片一删就再没有
    # 任何入口能引用到它。**旁路** —— 存储的临时故障不该让散片删不掉。
    key = clip.get("storage_key")
    if key:
        try:
            await get_public_storage().delete(key)
        except Exception as e:  # noqa: BLE001 — 删不掉只记日志
            logger.warning("clip 公网副本删除失败 clip_id=%s err=%s", clip_id, e)
    await clip_service.delete(db, clip_id)
    return {"ok": True}


@router.get("/{project_id}/clips/{clip_id}/file")
async def get_clip_file(project_id: str, clip_id: str, db: AsyncSession = Depends(get_db)):
    """回本地落地的 mp4。平台直链会过期,本地文件才是长期可播的那份。"""
    from pathlib import Path

    from fastapi.responses import FileResponse

    clip = await _get_clip_or_404(db, project_id, clip_id)
    path = Path(clip["local_path"] or "")
    if not clip["local_path"] or not path.is_file():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(path, media_type="video/mp4", filename=f"{clip_id}.mp4")
