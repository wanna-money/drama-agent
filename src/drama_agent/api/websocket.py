from fastapi import WebSocket
from typing import Any
import json
import asyncio


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        self._connections.setdefault(project_id, []).append(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket):
        if project_id in self._connections:
            try:
                self._connections[project_id].remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, project_id: str, event_type: str, data: Any):
        message = json.dumps({"type": event_type, "data": data})
        dead = []
        for ws in self._connections.get(project_id, []):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)


manager = ConnectionManager()
