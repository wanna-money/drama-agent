"""提示词端点(中立,供图像/关键帧/视频复用)。

两条路径:
  optimize —— 用户已写了粗描述,扩写它
  extract  —— 用户什么都没写,从作品内容(剧本正文/分镜)里提炼

extract 的原料**由后端自己取**(规范 4):前端只给 {subject, key} 与它所在的位置
(episode_id 或 project_id),不把剧本正文/分镜搬到前端再传回来。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from drama_agent.db.models import Episode, Project, Script
from drama_agent.db.session import get_db
from drama_agent.services import prompt_extract_service as extract_svc
from drama_agent.services import episode_service, story_service
from drama_agent.services.prompt_optimize_service import optimize_prompt

router = APIRouter(prefix="/api/prompt", tags=["prompt"])


class OptimizeIn(BaseModel):
    raw_prompt: str
    kind: str = "image"          # "image" | "video"
    target_model: str | None = None
    # 素材分类,追加该类的锁死项(四类各有,见 prompt_optimize_service._SUBJECT_BLOCKS)
    subject: str | None = None


@router.post("/optimize")
async def optimize(body: OptimizeIn):
    optimized = await optimize_prompt(
        body.raw_prompt, kind=body.kind, target_model=body.target_model, subject=body.subject)
    return {"optimized": optimized}


class ExtractIn(BaseModel):
    subject: str                      # "character" | "background"
    key: str                          # 角色名 / 场景地点
    episode_id: str | None = None     # 剧集侧(人物在确认角色时、背景在分镜后)
    project_id: str | None = None     # 改编侧(整本小说的角色确认)
    model: str | None = None


async def _episode_material(db: AsyncSession, subject: str, key: str, episode_id: str) -> str:
    """剧集侧原料。人物取源剧本正文 + 分析;背景取图状态里的分镜。

    分镜必须从图状态/快照取(与参考图面板同源),不从 Script —— 分镜是集级产物。
    """
    ep = (await db.execute(select(Episode).where(Episode.id == episode_id))).scalar_one_or_none()
    if ep is None:
        raise HTTPException(404, "剧集不存在")
    if subject == "background":
        from drama_agent.api.files import _reference_source
        source = await _reference_source(db, ep)
        return extract_svc.build_material(subject, key, shots=source.get("shots"))
    # 本集实际在拍的正文:优先版本树(集自己的内容),否则起始方案的正文
    prose = episode_service.seeded_screenplay(ep)
    if not prose.strip() and ep.script_id:
        sc = (await db.execute(
            select(Script).where(Script.id == ep.script_id))).scalar_one_or_none()
        prose = (sc.content if sc else "") or ""
    # 分析与原文经集的锚点取(权威在 Story)
    story = await story_service.row_of(db, ep.story_id or "")
    # 成稿剧本优于故事原文:它才是这一集实际拍的内容(人物在其中的样子更接近成片)。
    # 两者都是"含该角色的行文",对提炼外貌等价,故落到同一个 prose 参数。
    return extract_svc.build_material(
        subject, key,
        prose=(prose or (story.content if story else "") or ""),
        story_analysis=(story.story_analysis if story else None),
    )


async def _project_material(db: AsyncSession, subject: str, key: str, project_id: str) -> str:
    """改编侧原料:整本小说正文 + 切分前的角色分析。此侧只有人物(背景要等分镜)。"""
    p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "作品不存在")
    return extract_svc.build_material(
        subject, key, prose=p.source_text or "", story_analysis=p.cast_analysis)


@router.post("/extract")
async def extract(body: ExtractIn, db: AsyncSession = Depends(get_db)):
    """从作品内容提炼图像 prompt。

    错误分层:能力边界(道具/服饰不支持)与原料缺失都是 422 —— 两者都要引导用户改用手写,
    但 detail 不同,前端把它直接展示即可。定位不到 episode/project → 404(数据问题)。
    """
    key = (body.key or "").strip()
    if not key:
        raise HTTPException(422, "key 不能为空")
    try:
        if body.episode_id:
            material = await _episode_material(db, body.subject, key, body.episode_id)
        elif body.project_id:
            material = await _project_material(db, body.subject, key, body.project_id)
        else:
            raise HTTPException(422, "需要 episode_id 或 project_id 之一")
        prompt = await extract_svc.extract_prompt(body.subject, key, material, model=body.model)
    except (extract_svc.NotExtractable, extract_svc.NoMaterial) as e:
        raise HTTPException(422, str(e))
    return {"prompt": prompt}
