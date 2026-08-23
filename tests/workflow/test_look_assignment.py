import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _char(cid, name):
    m = MagicMock()
    m.id = cid
    m.name = name
    return m


def _look(lid, name, is_default=False):
    m = MagicMock()
    m.id = lid
    m.name = name
    m.is_default = is_default
    return m


def _state():
    return {"project_id": "p1", "look_assignments": {},
            "shots": [{"shot_id": "s1", "scene_number": 1, "characters": ["林夏"]},
                      {"shot_id": "s2", "scene_number": 2, "characters": ["林夏"]}]}


@pytest.mark.asyncio
async def test_look_assignment_llm_proposes_for_multi_look_char():
    import drama_agent.workflow.nodes.look_assignment as la
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "林夏")])), \
         patch("drama_agent.services.character_entity_service.list_looks",
               AsyncMock(return_value=[_look("l1", "日常装", True), _look("l2", "战斗装")])), \
         patch.object(la.llm_service, "complete_json",
                      AsyncMock(return_value={"1": {"林夏": "l1"}, "2": {"林夏": "l2"}})):
        out = await la.look_assignment_node(_state())
    assert out["look_assignments"] == {"1": {"林夏": "l1"}, "2": {"林夏": "l2"}}


@pytest.mark.asyncio
async def test_look_assignment_single_look_skips_llm_uses_default():
    """所有出场角色都只有 1 个 Look → 不调 LLM,全用默认。"""
    import drama_agent.workflow.nodes.look_assignment as la
    llm = AsyncMock()
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "林夏")])), \
         patch("drama_agent.services.character_entity_service.list_looks",
               AsyncMock(return_value=[_look("l1", "默认造型", True)])), \
         patch.object(la.llm_service, "complete_json", llm):
        out = await la.look_assignment_node(_state())
    llm.assert_not_awaited()
    assert out["look_assignments"]["1"]["林夏"] == "l1" and out["look_assignments"]["2"]["林夏"] == "l1"


@pytest.mark.asyncio
async def test_look_assignment_llm_failure_falls_back_to_default():
    import drama_agent.workflow.nodes.look_assignment as la
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "林夏")])), \
         patch("drama_agent.services.character_entity_service.list_looks",
               AsyncMock(return_value=[_look("l1", "日常装", True), _look("l2", "战斗装")])), \
         patch.object(la.llm_service, "complete_json", AsyncMock(side_effect=RuntimeError("x"))):
        out = await la.look_assignment_node(_state())
    # LLM 挂 → 回退默认 Look(l1)
    assert out["look_assignments"]["1"]["林夏"] == "l1"


@pytest.mark.asyncio
async def test_look_review_approve_and_reject():
    from drama_agent.workflow.graph import look_review_node, route_after_look_review
    st = {"look_assignments": {"1": {"林夏": "l1"}}, "shots": []}
    with patch("drama_agent.workflow.graph.interrupt", return_value={"approved": True}):
        out = await look_review_node(st)
    assert out["look_assignments_approved"] is True
    assert route_after_look_review({"look_assignments_approved": True}) == "prompt_engineer"
    # 拒绝 + 编辑
    with patch("drama_agent.workflow.graph.interrupt",
               return_value={"approved": False, "assignments": {"1": {"林夏": "l2"}}}):
        out = await look_review_node(st)
    assert out["look_assignments_approved"] is False
    assert out["look_assignments"] == {"1": {"林夏": "l2"}}  # 应用用户编辑
    assert route_after_look_review({"look_assignments_approved": False}) == "look_assignment"
