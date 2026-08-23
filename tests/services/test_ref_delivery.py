import base64

import pytest
from unittest.mock import AsyncMock, patch

from drama_agent.services.video_refs import RefImage, RefAudio
from drama_agent.services import ref_delivery


@pytest.mark.asyncio
async def test_local_view_and_voice_become_data_uri():
    store = AsyncMock()
    store.read.side_effect = lambda key: {"img.png": b"PNG", "v.wav": b"WAV"}[key]
    with patch.object(ref_delivery, "get_asset_storage", return_value=store):
        imgs, auds = await ref_delivery.inline_local_refs(
            [RefImage(url="/api/characters/view/img.png", kind="subject")],
            [RefAudio(url="/api/characters/voice/v.wav", subject_name="林夏")],
        )
    assert imgs[0].url == "data:image/png;base64," + base64.b64encode(b"PNG").decode()
    assert auds[0].url == "data:audio/wav;base64," + base64.b64encode(b"WAV").decode()
    assert auds[0].subject_name == "林夏"


@pytest.mark.asyncio
async def test_http_and_data_uri_passthrough():
    store = AsyncMock()
    with patch.object(ref_delivery, "get_asset_storage", return_value=store):
        imgs, auds = await ref_delivery.inline_local_refs(
            [RefImage(url="https://x/k.png", kind="first_frame"),
             RefImage(url="data:image/png;base64,AA", kind="subject")],
            [],
        )
    assert imgs[0].url == "https://x/k.png"
    assert imgs[1].url == "data:image/png;base64,AA"
    store.read.assert_not_awaited()
