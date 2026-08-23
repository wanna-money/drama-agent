import asyncio
import os
import socket
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from drama_agent.config import settings
from drama_agent.db.session import init_db
from drama_agent.api.projects import router as projects_router
from drama_agent.api.episodes import router as episodes_router
from drama_agent.api.workflow import router as workflow_router
from drama_agent.api.files import router as files_router, img_router as files_img_router
from drama_agent.api.config_api import router as config_router
from drama_agent.api.providers import router as providers_router
from drama_agent.api.artifacts import router as artifacts_router
from drama_agent.api.assets import router as assets_router
from drama_agent.api.characters import router as characters_router
from drama_agent.api.prompt import router as prompt_router
from drama_agent.api.scripts import router as scripts_router
from drama_agent.api.websocket import manager, backfill_events
from drama_agent.workflow.worker import JobWorker
import structlog

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    from drama_agent.workflow.graph import init_graphs
    await init_graphs()
    # 内置 provider 种子写入 DB(幂等),再从 DB 单表折入全部 provider
    from drama_agent.provider import rebuild_registry
    from drama_agent.provider.seed import seed_providers
    await seed_providers()
    await rebuild_registry()

    instance_id = settings.worker_instance_id or f"{socket.gethostname()}-{os.getpid()}"
    worker = JobWorker(
        instance_id=instance_id,
        poll_interval=settings.worker_poll_interval,
        heartbeat_timeout=settings.job_heartbeat_timeout,
    )
    app.state.job_worker = worker
    app.state.worker_task = asyncio.create_task(worker.run_forever())
    logger.info("Drama Agent started", host=settings.app_host, port=settings.app_port,
                instance_id=instance_id)
    yield
    await worker.stop()
    app.state.worker_task.cancel()
    logger.info("Drama Agent shutting down")


app = FastAPI(title="Drama Agent API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(episodes_router)
app.include_router(workflow_router)
app.include_router(files_router)
app.include_router(files_img_router)
app.include_router(config_router)
app.include_router(providers_router)
app.include_router(artifacts_router)
app.include_router(assets_router)
app.include_router(characters_router)
app.include_router(prompt_router)
app.include_router(scripts_router)


@app.websocket("/ws/episodes/{episode_id}")
async def websocket_endpoint(websocket: WebSocket, episode_id: str):
    last_seq = int(websocket.query_params.get("last_seq", 0) or 0)
    await manager.connect(episode_id, websocket)
    try:
        # 连上先补拉遗漏事件
        missed = await backfill_events(episode_id, last_seq)
        for ev in missed:
            await websocket.send_text(json.dumps({"type": ev["type"], "data": ev, "seq": ev["seq"]}))
            last_seq = max(last_seq, ev["seq"])
        # 短轮询推增量(SQLite 降级路径;PG 可后续换 LISTEN/NOTIFY)
        while True:
            await asyncio.sleep(settings.worker_poll_interval)
            fresh = await backfill_events(episode_id, last_seq)
            for ev in fresh:
                await websocket.send_text(json.dumps({"type": ev["type"], "data": ev, "seq": ev["seq"]}))
                last_seq = max(last_seq, ev["seq"])
    except WebSocketDisconnect:
        manager.disconnect(episode_id, websocket)
    except Exception:
        manager.disconnect(episode_id, websocket)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("drama_agent.main:app", host=settings.app_host, port=settings.app_port, reload=settings.debug)
