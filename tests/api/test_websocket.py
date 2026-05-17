"""Tests for WebSocket connection manager."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from drama_agent.api.websocket import ConnectionManager


@pytest.mark.asyncio
async def test_connect_and_broadcast():
    """Connect a WebSocket and receive a broadcast message."""
    manager = ConnectionManager()
    mock_ws = AsyncMock()

    await manager.connect("proj-1", mock_ws)
    mock_ws.accept.assert_awaited_once()

    await manager.broadcast("proj-1", "stage_change", {"stage": "analyzing"})
    mock_ws.send_text.assert_awaited_once()
    sent = json.loads(mock_ws.send_text.call_args[0][0])
    assert sent["type"] == "stage_change"
    assert sent["data"]["stage"] == "analyzing"


@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    """Disconnecting removes the WebSocket from active connections."""
    manager = ConnectionManager()
    mock_ws = AsyncMock()

    await manager.connect("proj-2", mock_ws)
    manager.disconnect("proj-2", mock_ws)

    await manager.broadcast("proj-2", "test", {})
    mock_ws.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_to_empty_project():
    """Broadcasting to a project with no connections does not raise."""
    manager = ConnectionManager()
    await manager.broadcast("no-such-project", "event", {"data": 1})


@pytest.mark.asyncio
async def test_dead_connection_cleaned_up():
    """A send failure removes the dead WebSocket from the pool."""
    manager = ConnectionManager()
    mock_ws = AsyncMock()
    mock_ws.send_text.side_effect = RuntimeError("connection closed")

    await manager.connect("proj-3", mock_ws)
    await manager.broadcast("proj-3", "test", {})

    # Dead connection should be removed after broadcast
    assert mock_ws not in manager._connections.get("proj-3", [])


@pytest.mark.asyncio
async def test_multiple_connections_same_project():
    """All connected clients receive the same broadcast."""
    manager = ConnectionManager()
    ws1, ws2 = AsyncMock(), AsyncMock()

    await manager.connect("proj-4", ws1)
    await manager.connect("proj-4", ws2)

    await manager.broadcast("proj-4", "update", {"n": 42})
    ws1.send_text.assert_awaited_once()
    ws2.send_text.assert_awaited_once()
    # Both received same message
    msg1 = json.loads(ws1.send_text.call_args[0][0])
    msg2 = json.loads(ws2.send_text.call_args[0][0])
    assert msg1 == msg2
    assert msg1["data"]["n"] == 42


@pytest.mark.asyncio
async def test_disconnect_nonexistent_is_safe():
    """Disconnecting a WebSocket not in the pool does not raise."""
    manager = ConnectionManager()
    mock_ws = AsyncMock()
    manager.disconnect("never-connected", mock_ws)
    manager.disconnect("proj-5", mock_ws)  # project exists but ws not in it
