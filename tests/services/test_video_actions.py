import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def builtin_registry():
    """装含内置声明的 registry 单例:video_actions.resolve_model 需能解析内置视频 model。
    registry 已收敛为仅 env+DB 合成,单测不跑 DB seed,故用代码内置声明直接构建。"""
    import drama_agent.provider as provider_pkg
    from drama_agent.provider.registry import ProviderRegistry
    orig = provider_pkg.provider_registry
    provider_pkg.provider_registry = ProviderRegistry(
        builtin=provider_pkg._builtin_providers(), custom_providers=[]
    )
    yield
    provider_pkg.provider_registry = orig


def _art(**over):
    base = dict(id="a1", project_id="p1", shot_id="s1", parent_id=None,
                provider="minimax", model="MiniMax-H3", resolution="768P",
                duration=5, action="generate", task_id="t1",
                video_url="http://v.mp4", local_path=None, prompt_text="a hero")
    base.update(over)
    return base


def test_available_actions_minimax_768p_has_all_three():
    from drama_agent.services.video_actions import available_actions
    ids = {a["id"] for a in available_actions(_art())}
    assert ids == {"rerun", "regenerate", "upscale"}


def test_available_actions_seedance_has_no_upscale():
    from drama_agent.services.video_actions import available_actions
    ids = {a["id"] for a in available_actions(_art(provider="seedance", resolution="1080p"))}
    assert ids == {"rerun", "regenerate"}


def test_upscale_unavailable_for_minimax_non_768p():
    from drama_agent.services.video_actions import available_actions
    ids = {a["id"] for a in available_actions(_art(resolution="2K"))}
    assert "upscale" not in ids


def test_regenerate_param_schema_uses_provider_resolutions():
    from drama_agent.services.video_actions import available_actions
    regen = next(a for a in available_actions(_art()) if a["id"] == "regenerate")
    res_field = next(f for f in regen["param_schema"] if f["name"] == "resolution")
    assert res_field["type"] == "enum"
    assert res_field["options"] == ["768P", "2K"]  # minimax resolutions from config


@pytest.mark.asyncio
async def test_rerun_execute_calls_create_task_with_source_props():
    from drama_agent.services.video_actions import ACTIONS
    fake = AsyncMock()
    fake.create_task = AsyncMock(return_value="new-task")
    fake.wait_for_task = AsyncMock(return_value=type("R", (), {
        "status": "succeeded", "video_url": "http://new.mp4", "last_frame_url": None, "error": None})())
    with patch("drama_agent.services.video_actions.video_service.get_provider", return_value=fake):
        new = await ACTIONS["rerun"].execute(_art(), {})
    fake.create_task.assert_awaited_once()
    kwargs = fake.create_task.call_args.kwargs
    assert kwargs["prompt"] == "a hero"
    assert kwargs["resolution"] == "768P"
    assert new["action"] == "rerun"
    assert new["task_id"] == "new-task"
    assert new["video_url"] == "http://new.mp4"
    assert new["provider"] == "minimax"


@pytest.mark.asyncio
async def test_upscale_execute_calls_create_regeneration():
    from drama_agent.services.video_actions import ACTIONS
    fake = AsyncMock()
    fake.create_regeneration = AsyncMock(return_value="re-task")
    fake.wait_for_task = AsyncMock(return_value=type("R", (), {
        "status": "succeeded", "video_url": "http://2k.mp4", "last_frame_url": None, "error": None})())
    with patch("drama_agent.services.video_actions.video_service.get_provider", return_value=fake):
        new = await ACTIONS["upscale"].execute(_art(), {})
    fake.create_regeneration.assert_awaited_once()
    assert fake.create_regeneration.call_args.kwargs["source_task_id"] == "t1"
    assert new["resolution"] == "2K"
    assert new["action"] == "upscale"


@pytest.mark.asyncio
async def test_regenerate_execute_uses_params():
    from drama_agent.services.video_actions import ACTIONS
    fake = AsyncMock()
    fake.create_task = AsyncMock(return_value="rg-task")
    fake.wait_for_task = AsyncMock(return_value=type("R", (), {
        "status": "succeeded", "video_url": "http://rg.mp4", "last_frame_url": None, "error": None})())
    with patch("drama_agent.services.video_actions.video_service.get_provider", return_value=fake):
        new = await ACTIONS["regenerate"].execute(
            _art(), {"resolution": "2K", "duration": 8, "prompt": "new prompt"})
    kwargs = fake.create_task.call_args.kwargs
    assert kwargs["resolution"] == "2K"
    assert kwargs["duration"] == 8
    assert kwargs["prompt"] == "new prompt"
    assert new["resolution"] == "2K"
    assert new["duration"] == 8
    assert new["prompt_text"] == "new prompt"


@pytest.mark.asyncio
async def test_rerun_replays_references_from_artifact():
    """#4: rerun 从产物 references_json 重建参考图并透传;子产物沿用参考图。"""
    from drama_agent.services import video_actions
    captured = {}

    async def cap_create(**kw):
        captured.update(kw)
        return "t2"
    fake = AsyncMock()
    fake.create_task = cap_create
    fake.wait_for_task = AsyncMock(return_value=type(
        "R", (), {"video_url": "http://v2.mp4", "last_frame_url": None,
                  "error": None, "status": "succeeded"})())
    art = _art(references_json=[
        {"url": "/api/characters/view/k1", "kind": "subject",
         "subject_name": "林夏", "view": "front"}])
    with patch("drama_agent.services.video_actions.video_service.get_provider", return_value=fake):
        new = await video_actions._rerun_execute(art, {})
    assert len(captured["references"]) == 1
    assert captured["references"][0].subject_name == "林夏"       # RefImage 重建正确
    assert new["references_json"] == art["references_json"]        # 子产物沿用,后续 rerun 仍可重放


def test_upscale_requires_provider_implements_create_regeneration(monkeypatch):
    """#10: 即便被误配声明了 upscale,provider 实例无 create_regeneration 也不放行。"""
    from drama_agent.services import video_actions
    monkeypatch.setattr(video_actions, "_supported_actions", lambda p: ["upscale"])
    art = _art(resolution="768P")

    class NoRegen:  # 不具备 create_regeneration(如 seedance)
        pass

    class WithRegen:
        async def create_regeneration(self, **k):
            return "t"
    assert video_actions._upscale_available(art, NoRegen()) is False
    assert video_actions._upscale_available(art, WithRegen()) is True
