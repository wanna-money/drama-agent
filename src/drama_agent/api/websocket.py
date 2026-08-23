from fastapi import WebSocket
from drama_agent.db import session as db_session
from drama_agent.services import event_service


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, episode_id: str, websocket: WebSocket):
        await websocket.accept()
        self._connections.setdefault(episode_id, []).append(websocket)

    def disconnect(self, episode_id: str, websocket: WebSocket):
        if episode_id in self._connections:
            try:
                self._connections[episode_id].remove(websocket)
            except ValueError:
                pass


manager = ConnectionManager()


async def backfill_events(episode_id: str, after_seq: int) -> list[dict]:
    """读取该集自 after_seq 之后的事件(WebSocket 补拉用)。"""
    async with db_session.AsyncSessionLocal() as s:
        return await event_service.fetch_since(s, episode_id, after_seq)
