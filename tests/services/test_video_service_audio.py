import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from drama_agent.services.video_refs import RefImage, RefAudio


@pytest.mark.asyncio
async def test_seedance_create_task_puts_audio_in_content():
    from drama_agent.services.video_service import SeedanceVideoService
    svc = SeedanceVideoService.__new__(SeedanceVideoService)  # 跳过 __init__(不建真 Ark client)
    svc.model = "ep-x"
    svc.max_reference_images = 9
    svc.provider_name = "seedance"
    created = MagicMock()
    created.id = "t1"
    svc._client = MagicMock()
    svc._client.content_generation.tasks.create = AsyncMock(return_value=created)
    tid = await svc.create_task(
        prompt="夜景对白",
        references=[RefImage(url="data:image/png;base64,AA", kind="subject", subject_name="林夏", view="front")],
        audio_refs=[RefAudio(url="data:audio/wav;base64,BB", subject_name="林夏")],
    )
    assert tid == "t1"
    sent = svc._client.content_generation.tasks.create.call_args.kwargs["content"]
    assert any(it.get("role") == "reference_audio" for it in sent)
    assert any(it.get("role") == "reference_image" for it in sent)
    assert "音色" in sent[0]["text"]


@pytest.mark.asyncio
async def test_seedance_audio_forces_reference_mode_not_first_frame():
    from drama_agent.services.video_service import SeedanceVideoService
    svc = SeedanceVideoService.__new__(SeedanceVideoService)
    svc.model = "ep-x"
    svc.max_reference_images = 9
    svc.provider_name = "seedance"
    created = MagicMock()
    created.id = "t2"
    svc._client = MagicMock()
    svc._client.content_generation.tasks.create = AsyncMock(return_value=created)
    await svc.create_task(
        prompt="p",
        references=[RefImage(url="https://x/ff.png", kind="first_frame")],
        audio_refs=[RefAudio(url="data:audio/wav;base64,BB", subject_name="林夏")],
    )
    sent = svc._client.content_generation.tasks.create.call_args.kwargs["content"]
    assert not any(it.get("role") == "first_frame" for it in sent)
    assert any(it.get("role") == "reference_audio" for it in sent)


def test_get_provider_seedance_2_5_uses_2_5_endpoint(monkeypatch):
    import drama_agent.services.video_service as vs
    monkeypatch.setattr(vs.settings, "seedance_2_5_endpoint_id", "ep-2p5")
    p = vs.video_service.get_provider("seedance-2.5")
    assert isinstance(p, vs.SeedanceVideoService) and p.model == "ep-2p5"


def test_get_provider_seedance_2_0_uses_default_endpoint(monkeypatch):
    import drama_agent.services.video_service as vs
    monkeypatch.setattr(vs.settings, "seedance_endpoint_id", "ep-2p0")
    p = vs.video_service.get_provider("seedance")
    assert isinstance(p, vs.SeedanceVideoService) and p.model == "ep-2p0"


@pytest.mark.asyncio
async def test_minimax_create_task_puts_audio_in_content():
    from drama_agent.services.video_service import MinimaxH3VideoService
    svc = MinimaxH3VideoService.__new__(MinimaxH3VideoService)
    svc.MODEL = "MiniMax-H3"
    svc.max_reference_images = 9
    svc.provider_name = "minimax"
    svc.BASE_URL = "https://api.minimaxi.com"
    svc._api_key = "k"
    with patch.object(
        MinimaxH3VideoService, "_request", new=AsyncMock(return_value={"task_id": "t9"})
    ) as req:
        tid = await svc.create_task(
            prompt="独白",
            references=[RefImage(url="data:image/png;base64,AA", kind="subject", subject_name="陆沉", view="front")],
            audio_refs=[RefAudio(url="data:audio/wav;base64,BB", subject_name="陆沉")],
        )
        body = req.call_args.kwargs["json"]
    assert tid == "t9"
    assert any(it.get("role") == "reference_audio" for it in body["content"])
    assert "音色" in body["content"][0]["text"]
