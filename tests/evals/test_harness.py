import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_run_eval_story_analyzer_scores_mocked_output():
    from drama_agent.evals import harness
    fake_json = {
        "title": "T", "setting": "s", "themes": ["a"],
        "characters": [{"name": "X", "appearance": "tall"}],
    }
    with patch("drama_agent.evals.harness.llm_service.complete_json",
               new=AsyncMock(return_value=fake_json)):
        report = await harness.run_eval("story_analyzer", model="m")
    assert report["node"] == "story_analyzer"
    assert report["passed"] is True
    assert len(report["results"]) >= 1
    assert all("scores" in r for r in report["results"])


@pytest.mark.asyncio
async def test_run_eval_unknown_node_raises():
    from drama_agent.evals import harness
    with pytest.raises(ValueError):
        await harness.run_eval("nope")
