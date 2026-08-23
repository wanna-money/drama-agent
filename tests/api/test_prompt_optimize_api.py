import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch


@pytest.fixture
async def client():
    from drama_agent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_optimize_endpoint_returns_optimized(client):
    with patch("drama_agent.api.prompt.optimize_prompt",
               AsyncMock(return_value="DETAILED PROMPT")):
        resp = await client.post("/api/prompt/optimize",
                                 json={"raw_prompt": "青衫侠客", "kind": "image"})
    assert resp.status_code == 200
    assert resp.json()["optimized"] == "DETAILED PROMPT"


@pytest.mark.asyncio
async def test_optimize_endpoint_empty_raw(client):
    with patch("drama_agent.api.prompt.optimize_prompt", AsyncMock(return_value="")):
        resp = await client.post("/api/prompt/optimize", json={"raw_prompt": "", "kind": "image"})
    assert resp.status_code == 200
    assert resp.json()["optimized"] == ""
