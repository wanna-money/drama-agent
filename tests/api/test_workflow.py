"""Tests for workflow API endpoints — start, resume, status."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
async def client():
    import drama_agent.db.session as db_session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from drama_agent.db.models import Base

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    original_engine = db_session.engine
    original_factory = db_session.AsyncSessionLocal
    db_session.engine = test_engine
    db_session.AsyncSessionLocal = test_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    from drama_agent.main import app
    from drama_agent.db.session import get_db
    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    db_session.engine = original_engine
    db_session.AsyncSessionLocal = original_factory
    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.fixture
async def project_id(client):
    resp = await client.post("/api/projects", json={
        "title": "Workflow Test",
        "raw_input": "A story",
        "genre": "drama",
        "video_provider": "seedance",
    })
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_workflow_status_on_created_project(client, project_id):
    """Status endpoint returns correct empty state for a new project."""
    with patch("drama_agent.api.workflow.get_graph") as mock_get_graph:
        mock_graph = AsyncMock()
        mock_state = MagicMock()
        mock_state.values = {}
        mock_state.next = []
        mock_graph.aget_state = AsyncMock(return_value=mock_state)
        mock_get_graph.return_value = mock_graph

        resp = await client.get(f"/api/projects/{project_id}/workflow/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project_id
        assert data["db_status"] == "created"
        assert data["shots"] == []
        assert data["prompts"] == []
        assert data["videos"] == []
        assert data["next"] == []


@pytest.mark.asyncio
async def test_workflow_status_not_found(client):
    """Status for nonexistent project returns 404."""
    with patch("drama_agent.api.workflow.get_graph") as mock_get_graph:
        mock_get_graph.return_value = AsyncMock()
        resp = await client.get("/api/projects/does-not-exist/workflow/status")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_workflow_not_found(client):
    """Starting workflow for nonexistent project returns 404."""
    resp = await client.post("/api/projects/does-not-exist/workflow/start")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_workflow_success(client, project_id):
    """Starting a created project queues the background task and returns ok."""
    with patch("drama_agent.api.workflow._run_workflow", new_callable=AsyncMock):
        resp = await client.post(f"/api/projects/{project_id}/workflow/start")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_start_workflow_already_started(client, project_id):
    """Starting a workflow that's already running returns 409."""
    # First start
    with patch("drama_agent.api.workflow._run_workflow", new_callable=AsyncMock):
        await client.post(f"/api/projects/{project_id}/workflow/start")

    # Manually set status to something non-created
    from drama_agent.db.session import AsyncSessionLocal
    from drama_agent.db.models import Project
    from sqlalchemy import select
    import drama_agent.db.session as db_session
    # Use test session factory
    async with db_session.AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        p = result.scalar_one()
        p.status = "analyzing"
        await db.commit()

    with patch("drama_agent.api.workflow._run_workflow", new_callable=AsyncMock):
        resp = await client.post(f"/api/projects/{project_id}/workflow/start")
        assert resp.status_code == 409


@pytest.mark.asyncio
async def test_resume_workflow_success(client, project_id):
    """Resume endpoint dispatches task and returns ok."""
    with patch("drama_agent.api.workflow._resume_workflow", new_callable=AsyncMock):
        resp = await client.post(
            f"/api/projects/{project_id}/workflow/resume",
            json={"approved": True, "notes": "", "edited_prompts": {}},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_safe_state_summary_all_fields():
    """_safe_state_summary returns all expected keys."""
    from drama_agent.api.workflow import _safe_state_summary
    state = {
        "title": "Test",
        "current_stage": "screenplay_written",
        "story_analysis": {"title": "T", "genre": "drama"},
        "screenplay": "INT. CITY - DAY\n\nHero enters.",
        "shots": [{"shot_id": "s1"}],
        "prompts": [{"shot_id": "s1", "prompt_text": "epic"}],
        "videos": [],
        "assembled_video_path": "/output/final.mp4",
        "raw_input": "this should be excluded",
        "character_references": {"Hero": "http://img.jpg"},
    }
    summary = _safe_state_summary(state)
    assert summary["title"] == "Test"
    assert summary["current_stage"] == "screenplay_written"
    assert summary["screenplay"] == state["screenplay"]
    assert len(summary["shots"]) == 1
    assert len(summary["prompts"]) == 1
    assert summary["assembled_video_path"] == "/output/final.mp4"
    assert "raw_input" not in summary
    assert "character_references" not in summary


@pytest.mark.asyncio
async def test_workflow_status_with_langgraph_state(client, project_id):
    """Status endpoint merges LangGraph state into response."""
    with patch("drama_agent.api.workflow.get_graph") as mock_get_graph:
        mock_graph = AsyncMock()
        mock_state = MagicMock()
        mock_state.values = {
            "current_stage": "screenplay_written",
            "screenplay": "INT. CITY\n\nHero walks.",
            "shots": [],
            "prompts": [],
            "videos": [],
            "assembled_video_path": None,
            "story_analysis": {"title": "T"},
        }
        mock_state.next = ("screenplay_review",)
        mock_graph.aget_state = AsyncMock(return_value=mock_state)
        mock_get_graph.return_value = mock_graph

        resp = await client.get(f"/api/projects/{project_id}/workflow/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_stage"] == "screenplay_written"
        assert "screenplay_review" in data["next"]
        assert data["screenplay"] is not None
