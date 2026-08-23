import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from drama_agent.services import video_actions as va


@pytest.mark.asyncio
async def test_regenerate_inlines_refs_and_carries_audio():
    artifact = {
        "id": "a1", "project_id": "p1", "shot_id": "s1", "provider": "seedance",
        "resolution": "1080p", "duration": 5, "prompt_text": "夜景",
        "references_json": [{"url": "/api/characters/view/f.png", "kind": "subject",
                             "subject_name": "林夏", "view": "front"}],
        "audio_refs_json": [{"url": "/api/characters/voice/v.wav", "subject_name": "林夏"}],
    }
    fake_provider = MagicMock()
    fake_provider.create_task = AsyncMock(return_value="t1")
    fake_provider.wait_for_task = AsyncMock(return_value=MagicMock(video_url="http://v/1.mp4"))

    async def fake_inline(refs, auds):
        for r in refs:
            r.url = "data:image/png;base64,AA"
        for a in auds:
            a.url = "data:audio/wav;base64,BB"
        return refs, auds

    with patch.object(va.video_service, "get_provider", return_value=fake_provider), \
         patch("drama_agent.services.ref_delivery.inline_local_refs", new=fake_inline):
        new = await va._regenerate_execute(artifact, {})

    kwargs = fake_provider.create_task.call_args.kwargs
    assert kwargs["references"][0].url.startswith("data:image/")
    assert kwargs["audio_refs"][0].url.startswith("data:audio/")
    assert new["audio_refs_json"] == artifact["audio_refs_json"]
