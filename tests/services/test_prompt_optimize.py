import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_image_prompt_guide_retrievable():
    from drama_agent.knowledge.store import MarkdownKnowledgeStore
    out = MarkdownKnowledgeStore().retrieve("image_prompt_guide")
    assert out and "扩写公式" in out[0] and "反模式" in out[0]


@pytest.mark.asyncio
async def test_optimize_image_uses_retrieved_rules():
    from drama_agent.services import prompt_optimize_service as svc
    with patch.object(svc, "knowledge_store", MagicMock(
             retrieve=MagicMock(return_value=["IMG_RULES_BLOCK"]))), \
         patch.object(svc.llm_service, "complete",
                      AsyncMock(return_value="OPTIMIZED PROMPT")) as llm:
        out = await svc.optimize_prompt("青衫侠客", kind="image")
    assert out == "OPTIMIZED PROMPT"
    # 规则 + 原文都进了给 LLM 的 user prompt
    user_arg = llm.call_args.args[1] if len(llm.call_args.args) > 1 else llm.call_args.kwargs.get("user", "")
    assert "IMG_RULES_BLOCK" in user_arg and "青衫侠客" in user_arg


@pytest.mark.asyncio
async def test_optimize_empty_returns_raw():
    from drama_agent.services import prompt_optimize_service as svc
    assert await svc.optimize_prompt("   ", kind="image") == ""


@pytest.mark.asyncio
async def test_optimize_llm_failure_returns_raw():
    from drama_agent.services import prompt_optimize_service as svc
    with patch.object(svc, "knowledge_store", MagicMock(retrieve=MagicMock(return_value=["R"]))), \
         patch.object(svc.llm_service, "complete", AsyncMock(side_effect=RuntimeError("x"))):
        assert await svc.optimize_prompt("原始描述", kind="image") == "原始描述"


@pytest.mark.asyncio
async def test_optimize_video_uses_prompt_guide_by_model():
    from drama_agent.services import prompt_optimize_service as svc
    import drama_agent.provider as pp
    m = MagicMock()
    m.prompt_guide_key = "seedance"
    reg = MagicMock()
    reg.resolve_model = MagicMock(return_value=(MagicMock(), m))
    ks = MagicMock()
    ks.retrieve = MagicMock(return_value=["SEEDANCE_RULES"])
    with patch.object(pp, "provider_registry", reg), \
         patch.object(svc, "knowledge_store", ks), \
         patch.object(svc.llm_service, "complete", AsyncMock(return_value="OUT")):
        out = await svc.optimize_prompt("跳舞", kind="video", target_model="seedance")
    assert out == "OUT"
    ks.retrieve.assert_called_with("prompt_guide", key="seedance")


@pytest.mark.asyncio
async def test_optimize_character_subject_adds_four_view(monkeypatch):
    from drama_agent.services import prompt_optimize_service as p
    from unittest.mock import AsyncMock
    captured = {}

    async def fake_complete(system, user, temperature=0.5, model=None):
        captured["system"] = system
        captured["user"] = user
        return "OUT"

    monkeypatch.setattr(p.llm_service, "complete", AsyncMock(side_effect=fake_complete))
    monkeypatch.setattr(p, "_default_llm_model", lambda: "m")
    await p.optimize_prompt("一个女侠", kind="image", subject="character")
    blob = captured["system"] + captured["user"]
    assert "面部特写" in blob and "四视图" in blob


@pytest.mark.asyncio
async def test_optimize_non_character_no_four_view(monkeypatch):
    from drama_agent.services import prompt_optimize_service as p
    from unittest.mock import AsyncMock
    captured = {}

    async def fake_complete(system, user, temperature=0.5, model=None):
        captured["blob"] = system + user
        return "OUT"

    monkeypatch.setattr(p.llm_service, "complete", AsyncMock(side_effect=fake_complete))
    monkeypatch.setattr(p, "_default_llm_model", lambda: "m")
    await p.optimize_prompt("一栋楼", kind="image", subject=None)
    assert "四视图" not in captured["blob"]


@pytest.mark.asyncio
async def test_default_llm_model_prefers_marked_default(monkeypatch):
    from drama_agent.services import prompt_optimize_service as p
    from drama_agent.provider.base import Model

    class _Reg:
        # 有效默认 = is_default 优先,否则首个可用(此处 is_default 命中)
        def effective_default(self, kind):
            return Model(id="deepseek-v4-flash-0731", label="DS",
                         provider="ds", kind="llm")

    import drama_agent.provider as pp
    monkeypatch.setattr(pp, "provider_registry", _Reg())
    assert p._default_llm_model() == "deepseek-v4-flash-0731"


@pytest.mark.asyncio
async def test_default_llm_model_falls_back_to_first_available(monkeypatch):
    """无 is_default 默认时,退回第一个可用。"""
    from drama_agent.services import prompt_optimize_service as p
    from drama_agent.provider.base import Model

    class _Reg:
        # 无 is_default → 有效默认退回首个可用
        def effective_default(self, kind):
            return Model(id="deepseek-v4-flash", label="DS", provider="drama", kind="llm")

    import drama_agent.provider as pp
    monkeypatch.setattr(pp, "provider_registry", _Reg())
    assert p._default_llm_model() == "deepseek-v4-flash"
