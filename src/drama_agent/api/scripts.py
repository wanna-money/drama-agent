"""scripts API:剧本创作(ScriptGraph)+ 全局剧本库 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from drama_agent.db.session import get_db
from drama_agent.db.enums import LifecycleStatus, JobKind, EventType, Genre
from drama_agent import provider as provider_pkg
from drama_agent.services import (
    script_service, job_service, event_service, screenplay_revise_service,
)
from drama_agent.workflow.graph import get_script_graph

router = APIRouter(prefix="/api/scripts", tags=["scripts"])


class CreateScriptRequest(BaseModel):
    title: str
    genre: Genre = Genre.DRAMA
    source_text: str
    project_id: str | None = None
    llm_model: str = ""


class UpdateScriptRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class ScriptResumeRequest(BaseModel):
    approved: bool
    notes: str = ""
    edited_prompts: dict[str, str] = {}


class ReviseMessage(BaseModel):
    role: str
    content: str


class ReviseRequest(BaseModel):
    messages: list[ReviseMessage]


class EditScreenplayRequest(BaseModel):
    screenplay: str


class RevertRequest(BaseModel):
    version_index: int


@router.post("")
async def create_script(req: CreateScriptRequest, db: AsyncSession = Depends(get_db)):
    """建剧本草稿 + 入队 SCRIPT_START 立即生成正文。"""
    row = await script_service.create(
        db, title=req.title, genre=req.genre.value,
        source_text=req.source_text, project_id=req.project_id,
        llm_model=req.llm_model,
    )
    job = await job_service.enqueue(
        db, JobKind.SCRIPT_START, row["id"], dedup_key="script_start",
        project_id=req.project_id or "",
    )
    await event_service.append_event(
        db, row["id"], EventType.STAGE_CHANGE, {"lifecycle": "queued"},
        project_id=req.project_id or "",
    )
    return {**row, "job_id": job["id"], "status": LifecycleStatus.QUEUED.value}


@router.get("")
async def list_scripts(project_id: str | None = None, db: AsyncSession = Depends(get_db)):
    return await script_service.list_scripts(db, project_id=project_id)


@router.get("/{script_id}")
async def get_script(script_id: str, db: AsyncSession = Depends(get_db)):
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return row


@router.get("/{script_id}/status")
async def get_script_status(script_id: str, db: AsyncSession = Depends(get_db)):
    st = await script_service.get_status(db, script_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return st


@router.put("/{script_id}")
async def update_script(script_id: str, req: UpdateScriptRequest, db: AsyncSession = Depends(get_db)):
    row = await script_service.update(db, script_id, title=req.title, content=req.content)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    return row


@router.delete("/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    ok = await script_service.delete(db, script_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Script not found")
    return {"ok": True}


@router.post("/{script_id}/start")
async def start_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """对草稿(created)或失败(failed)的剧本入队 SCRIPT_START 生成/重试正文。"""
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    if row["status"] not in (LifecycleStatus.CREATED.value, LifecycleStatus.FAILED.value):
        raise HTTPException(status_code=409, detail=f"Script not startable (status: {row['status']})")
    job = await job_service.enqueue(
        db, JobKind.SCRIPT_START, script_id, dedup_key="script_start",
        project_id=row.get("project_id") or "",
    )
    await event_service.append_event(
        db, script_id, EventType.STAGE_CHANGE, {"lifecycle": "queued"},
        project_id=row.get("project_id") or "",
    )
    return {"ok": True, "job_id": job["id"], "message": "Script generation queued"}


@router.post("/{script_id}/retry")
async def retry_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """重试生成:重置该剧本的工作流线程(清 checkpointer)+ 清空旧产物 + 重新入队 SCRIPT_START,
    从头重跑。用于生成失败(failed)或中断卡住(paused 但无内容)的剧本。运行中(queued/running)拒绝。"""
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    if row["status"] in (LifecycleStatus.QUEUED.value, LifecycleStatus.RUNNING.value):
        raise HTTPException(status_code=409, detail=f"Script is running (status: {row['status']})")
    # 重置该剧本的 checkpointer 线程 → 从头重跑(而非从旧检查点恢复)。线程不存在/删除失败不阻断。
    graph = await get_script_graph()
    try:
        await graph.checkpointer.adelete_thread(script_id)
    except Exception:  # noqa: BLE001 — 无线程或删除失败不应阻断重试
        pass
    await script_service.reset_for_retry(db, script_id)
    job = await job_service.enqueue(
        db, JobKind.SCRIPT_START, script_id, dedup_key="script_start",
        project_id=row.get("project_id") or "",
    )
    await event_service.append_event(
        db, script_id, EventType.STAGE_CHANGE, {"lifecycle": "queued"},
        project_id=row.get("project_id") or "",
    )
    return {"ok": True, "job_id": job["id"], "message": "Script retry queued"}


@router.post("/{script_id}/resume")
async def resume_script(script_id: str, req: ScriptResumeRequest, db: AsyncSession = Depends(get_db)):
    """剧本审核通过/打回 → 入队 SCRIPT_RESUME(dedup 按中断点)。"""
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    graph = await get_script_graph()
    config = {"configurable": {"thread_id": script_id}}
    state = await graph.aget_state(config)
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if not next_nodes:
        raise HTTPException(status_code=409, detail="Script is not paused at a review step")
    dedup_key = "resume:" + "-".join(next_nodes)
    payload = {"approved": req.approved, "notes": req.notes, "edited_prompts": req.edited_prompts}
    job = await job_service.enqueue(
        db, JobKind.SCRIPT_RESUME, script_id, dedup_key=dedup_key, payload=payload,
        project_id=row.get("project_id") or "",
    )
    await event_service.append_event(
        db, script_id, EventType.STAGE_CHANGE, {"lifecycle": "queued", "resume": True},
        project_id=row.get("project_id") or "",
    )
    return {"ok": True, "job_id": job["id"], "message": "Script resume queued"}


async def _require_paused_review(script_id: str, db: AsyncSession):
    """审核态三个端点(revise/edit_screenplay/revert)共用守卫:剧本存在 + 图暂停在 screenplay_review。
    返回 (row, graph, config, current_screenplay);不满足则直接抛 HTTPException。"""
    row = await script_service.get(db, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    graph = await get_script_graph()
    config = {"configurable": {"thread_id": script_id}}
    state = await graph.aget_state(config)
    next_nodes = tuple(state.next) if state and getattr(state, "next", ()) else ()
    if "screenplay_review" not in next_nodes:
        raise HTTPException(status_code=409, detail="Script is not paused at screenplay review")
    current = (getattr(state, "values", None) or {}).get("screenplay")
    return row, graph, config, current


@router.post("/{script_id}/revise")
async def revise_script(script_id: str, req: ReviseRequest, db: AsyncSession = Depends(get_db)):
    """对话式改写:确认-执行 agent 单轮决策。action=ask 只回复不改剧本;
    action=apply 才追加版本 + 写回 checkpointer(见 screenplay_revise_service.turn 的降级兜底)。"""
    row, graph, config, current = await _require_paused_review(script_id, db)
    model = row.get("llm_model") or ""
    if not model:
        default_model = provider_pkg.provider_registry.effective_default("llm")
        model = default_model.id if default_model else ""
    if not model:
        raise HTTPException(status_code=500, detail="No LLM model configured")

    result = await screenplay_revise_service.turn(
        current or "", [m.model_dump() for m in req.messages], model,
    )
    if result["action"] != "apply":
        return {"action": "ask", "reply": result["reply"]}

    version = await script_service.append_screenplay_version(
        db, script_id, new_screenplay=result["screenplay"], seed_screenplay=current or "",
        label=result["summary"] or "AI 改写",
    )
    await graph.aupdate_state(config, {"screenplay": result["screenplay"]})
    return {
        "action": "apply", "reply": result["reply"], "screenplay": result["screenplay"],
        "version_index": version["version_index"], "versions_len": version["versions_len"],
    }


@router.post("/{script_id}/edit_screenplay")
async def edit_screenplay(
    script_id: str, req: EditScreenplayRequest, db: AsyncSession = Depends(get_db)
):
    """手动编辑剧本全文:落一个新版本(label「手动编辑」)+ 写回 checkpointer。
    先过状态守卫(404/409)再校验正文非空(422)——与 REST 惯例一致:资源状态先于请求体校验。"""
    _row, graph, config, current = await _require_paused_review(script_id, db)
    if not req.screenplay.strip():
        raise HTTPException(status_code=422, detail="screenplay must not be blank")
    version = await script_service.append_screenplay_version(
        db, script_id, new_screenplay=req.screenplay, seed_screenplay=current or "",
        label="手动编辑",
    )
    await graph.aupdate_state(config, {"screenplay": req.screenplay})
    return {"screenplay": req.screenplay, "version_index": version["version_index"]}


@router.post("/{script_id}/revert")
async def revert_screenplay(
    script_id: str, req: RevertRequest, db: AsyncSession = Depends(get_db)
):
    """回退到历史版本:切换 current + 写回 checkpointer(通过时用回退后的版本)。"""
    _row, graph, config, _current = await _require_paused_review(script_id, db)
    try:
        version = await script_service.set_current_version(db, script_id, req.version_index)
    except IndexError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await graph.aupdate_state(config, {"screenplay": version["screenplay"]})
    return version
