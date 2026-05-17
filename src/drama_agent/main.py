import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from drama_agent.config import settings
from drama_agent.db.session import init_db
from drama_agent.api.projects import router as projects_router
from drama_agent.api.workflow import router as workflow_router
from drama_agent.api.files import router as files_router
from drama_agent.api.config_api import router as config_router
from drama_agent.api.websocket import manager
import structlog

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.chroma_dir).mkdir(parents=True, exist_ok=True)
    from drama_agent.workflow.graph import init_graph
    await init_graph()
    logger.info("Drama Agent started", host=settings.app_host, port=settings.app_port)
    yield
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
app.include_router(workflow_router)
app.include_router(files_router)
app.include_router(config_router)


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("drama_agent.main:app", host=settings.app_host, port=settings.app_port, reload=settings.debug)
