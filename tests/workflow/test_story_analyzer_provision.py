import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _analysis():
    return {"title": "T", "characters": [
        {"name": "林夏", "appearance": "女, 长发"},
        {"name": "陆沉", "appearance": "男, 短发"},
    ]}


@pytest.mark.asyncio
async def test_story_analyzer_auto_creates_missing_characters():
    import drama_agent.workflow.nodes.story_analyzer as sa
    created = []
    ce = MagicMock()
    ce.list_characters = AsyncMock(return_value=[MagicMock(name="陆沉")])  # 陆沉已存在
    ce.create_character = AsyncMock(side_effect=lambda pid, n, d=None: created.append(n))
    # MagicMock(name=...) 的 .name 是 mock 名而非属性;显式设属性
    ce.list_characters.return_value[0].name = "陆沉"
    with patch.object(sa.llm_service, "complete_json", AsyncMock(return_value=_analysis())), \
         patch.object(sa, "character_service", MagicMock(save=AsyncMock())), \
         patch("drama_agent.services.character_entity_service.list_characters", ce.list_characters), \
         patch("drama_agent.services.character_entity_service.create_character", ce.create_character):
        out = await sa.story_analyzer_node({"raw_input": "x", "genre": "drama",
                                            "project_id": "p1", "title": "T", "llm_model": None})
    assert created == ["林夏"]  # 只建缺失的林夏,陆沉已存在跳过
    assert out["story_analysis"]["title"] == "T"


@pytest.mark.asyncio
async def test_story_analyzer_provision_failure_does_not_break():
    import drama_agent.workflow.nodes.story_analyzer as sa
    with patch.object(sa.llm_service, "complete_json", AsyncMock(return_value=_analysis())), \
         patch.object(sa, "character_service", MagicMock(save=AsyncMock())), \
         patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(side_effect=RuntimeError("db down"))):
        out = await sa.story_analyzer_node({"raw_input": "x", "genre": "drama",
                                            "project_id": "p1", "title": "T", "llm_model": None})
    assert out["story_analysis"]["title"] == "T"  # 自动建壳失败不阻断
