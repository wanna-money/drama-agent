import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from drama_agent.services.video_refs import RefImage, RefAudio
from drama_agent.workflow.nodes import video_generator as vg


class _Char:
    def __init__(self, cid, voice_key):
        self.id = cid
        self.voice_key = voice_key


@pytest.mark.asyncio
async def test_audio_refs_for_shot_each_character_its_own_voice():
    shot = {"characters": ["林夏", "陆沉", "路人"]}
    async def fake_get(pid, name):
        return {"林夏": _Char("c1", "a.wav"), "陆沉": _Char("c2", "b.mp3"),
                "路人": _Char("c3", None)}.get(name)
    with patch("drama_agent.services.character_entity_service.get_character_by_name", new=fake_get):
        auds = await vg._audio_refs_for_shot("p1", shot)
    urls = {a.subject_name: a.url for a in auds}
    assert urls == {"林夏": "/api/characters/voice/a.wav", "陆沉": "/api/characters/voice/b.mp3"}


@pytest.mark.asyncio
async def test_audio_refs_for_shot_join_failure_skips_not_raises():
    shot = {"characters": ["X"]}
    async def boom(pid, name):
        raise RuntimeError("db down")
    with patch("drama_agent.services.character_entity_service.get_character_by_name", new=boom):
        assert await vg._audio_refs_for_shot("p1", shot) == []


@pytest.mark.asyncio
async def test_resolve_audio_refs_gated_by_capability():
    model = MagicMock()
    model.supports_audio_reference = False
    with patch("drama_agent.provider.provider_registry.resolve_model",
               return_value=(MagicMock(), model)):
        out = await vg._resolve_audio_refs("minimax", "p1", {"characters": ["林夏"]},
                                           [RefImage(url="/api/characters/view/f.png", kind="subject")])
    assert out == []


@pytest.mark.asyncio
async def test_resolve_audio_refs_caps_and_mutex_degrades():
    model = MagicMock()
    model.supports_audio_reference = True
    model.max_reference_audios = 3
    auds5 = [RefAudio(url=f"/api/characters/voice/{i}.wav", subject_name=str(i)) for i in range(5)]
    with patch("drama_agent.provider.provider_registry.resolve_model",
               return_value=(MagicMock(), model)), \
         patch.object(vg, "_audio_refs_for_shot", new=AsyncMock(return_value=auds5)):
        capped = await vg._resolve_audio_refs("seedance", "p1", {}, [RefImage(url="/api/characters/view/f.png", kind="subject")])
        assert len(capped) == 3
        dropped = await vg._resolve_audio_refs("seedance", "p1", {}, [])
        assert dropped == []
