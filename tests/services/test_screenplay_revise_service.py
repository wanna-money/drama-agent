import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_turn_apply_returns_new_screenplay_and_summary():
    from drama_agent.services import screenplay_revise_service as svc
    fake_result = {
        "action": "apply",
        "reply": "已按你的要求改好了。",
        "screenplay": "第一场 海边\n改写后的内容",
        "summary": "改成轻松基调",
    }
    with patch.object(svc.llm_service, "complete_json", AsyncMock(return_value=fake_result)):
        result = await svc.turn(
            current_screenplay="第一场 海边\n原内容",
            messages=[
                {"role": "user", "content": "把基调改轻松一点"},
                {"role": "assistant", "content": "好的,计划是把台词改幽默,确认吗?"},
                {"role": "user", "content": "确认"},
            ],
            model="deepseek-v4-flash-0731",
        )

    assert result == {
        "action": "apply", "reply": "已按你的要求改好了。",
        "screenplay": "第一场 海边\n改写后的内容", "summary": "改成轻松基调",
    }


@pytest.mark.asyncio
async def test_turn_ask_does_not_include_screenplay():
    from drama_agent.services import screenplay_revise_service as svc
    fake_result = {"action": "ask", "reply": "你想具体改哪一场?"}
    with patch.object(svc.llm_service, "complete_json", AsyncMock(return_value=fake_result)):
        result = await svc.turn(
            current_screenplay="正文",
            messages=[{"role": "user", "content": "改一下"}],
            model="m",
        )

    assert result["action"] == "ask"
    assert result["reply"] == "你想具体改哪一场?"
    assert result["screenplay"] is None


@pytest.mark.asyncio
async def test_turn_apply_with_blank_screenplay_downgrades_to_ask():
    """LLM 声称 apply 却给了空剧本(空字符串/纯空白)—— 必须降级为 ask,绝不让空剧本被上层写回。"""
    from drama_agent.services import screenplay_revise_service as svc
    fake_result = {"action": "apply", "reply": "改好了", "screenplay": "   ", "summary": "x"}
    with patch.object(svc.llm_service, "complete_json", AsyncMock(return_value=fake_result)):
        result = await svc.turn(
            current_screenplay="正文", messages=[{"role": "user", "content": "改"}], model="m"
        )

    assert result["action"] == "ask"
    assert result["screenplay"] is None
    assert result["reply"]  # 非空,给用户一个可读的回退提示


@pytest.mark.asyncio
async def test_turn_malformed_llm_output_downgrades_to_ask():
    """complete_json 解析失败时按既有约定返回 {}(见 llm_service._parse_json);
    turn 必须兜底,不能让空 dict 传播成 KeyError 或误判成 apply。"""
    from drama_agent.services import screenplay_revise_service as svc
    with patch.object(svc.llm_service, "complete_json", AsyncMock(return_value={})):
        result = await svc.turn(
            current_screenplay="正文", messages=[{"role": "user", "content": "改"}], model="m"
        )

    assert result["action"] == "ask"
    assert result["screenplay"] is None
    assert result["reply"]


@pytest.mark.asyncio
async def test_turn_non_dict_llm_output_downgrades_to_ask():
    """complete_json 虽标注 -> dict,顶层是 JSON 数组时会真返回 list;
    turn 必须与 {} 同样降级为 ask,不能在 .get() 上炸成 AttributeError/500。"""
    from drama_agent.services import screenplay_revise_service as svc
    fake = AsyncMock(return_value=["not", "a", "dict"])
    with patch.object(svc.llm_service, "complete_json", fake):
        result = await svc.turn(
            current_screenplay="正文", messages=[{"role": "user", "content": "改"}], model="m"
        )

    assert result["action"] == "ask"
    assert result["screenplay"] is None
    assert result["reply"]


def test_build_user_prompt_includes_screenplay_and_history():
    from drama_agent.services import screenplay_revise_service as svc
    prompt = svc.build_user_prompt(
        current_screenplay="第一场 海边",
        messages=[
            {"role": "user", "content": "把台词改幽默"},
            {"role": "assistant", "content": "计划是..."},
        ],
    )
    assert "第一场 海边" in prompt
    assert "把台词改幽默" in prompt
    assert "计划是..." in prompt
