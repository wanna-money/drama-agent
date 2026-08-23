"""image protocol:测我们对 Ark/OpenAI images 的用法与 b64/url→bytes 拉平。"""
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from drama_agent.provider.base import Model, Provider
from drama_agent.provider.image.protocols import (
    DoubaoImageProtocol, OpenAIImageProtocol, ImageResult, get_image_protocol,
)

_PNG = b"\x89PNG\r\n\x1a\n"


def _provider(protocol="doubao-image"):
    return Provider(id="img", label="Img", protocol=protocol, api_key="sk-x",
                    models=[Model(id="m", label="m", provider="img", kind="image")])


def _model():
    return Model(id="m", label="m", provider="img", kind="image")


@pytest.mark.asyncio
async def test_doubao_generate_decodes_b64():
    client = MagicMock()
    item = MagicMock()
    item.b64_json = base64.b64encode(_PNG).decode()
    item.url = None
    resp = MagicMock()
    resp.data = [item]
    client.images.generate = AsyncMock(return_value=resp)
    proto = DoubaoImageProtocol()
    with patch.object(proto, "_client", return_value=client):
        result = await proto.generate(_provider(), _model(), prompt="a cat", size="1024x1024", n=1)
    assert isinstance(result, ImageResult)
    assert result.images == [_PNG]


@pytest.mark.asyncio
async def test_doubao_generate_downloads_url_when_no_b64():
    client = MagicMock()
    item = MagicMock()
    item.b64_json = None
    item.url = "https://x/img.png"
    resp = MagicMock()
    resp.data = [item]
    client.images.generate = AsyncMock(return_value=resp)
    proto = DoubaoImageProtocol()
    with patch.object(proto, "_client", return_value=client), \
         patch.object(proto, "_download", new=AsyncMock(return_value=_PNG)):
        result = await proto.generate(_provider(), _model(), prompt="a cat", size=None, n=1)
    assert result.images == [_PNG]


@pytest.mark.asyncio
async def test_doubao_generate_omits_n_and_loops_for_batch():
    """Ark(Seedream)images.generate 无 n 参数:必须不传 n(否则真 SDK 抛 TypeError),
    且 n>1 时循环多次调用以兑现"返回 n 张"契约。"""
    client = MagicMock()
    item = MagicMock()
    item.b64_json = base64.b64encode(_PNG).decode()
    item.url = None
    resp = MagicMock()
    resp.data = [item]
    client.images.generate = AsyncMock(return_value=resp)
    proto = DoubaoImageProtocol()
    with patch.object(proto, "_client", return_value=client):
        result = await proto.generate(_provider(), _model(), prompt="a cat", size="1024x1024", n=2)
    assert client.images.generate.call_count == 2                 # n 张 = n 次调用
    for call in client.images.generate.call_args_list:
        assert "n" not in call.kwargs                             # 绝不给 Ark 传 n
    assert result.images == [_PNG, _PNG]


@pytest.mark.asyncio
async def test_doubao_edit_not_supported():
    proto = DoubaoImageProtocol()
    with pytest.raises(NotImplementedError):
        await proto.edit(_provider(), _model(), image=_PNG, prompt="x", mask=None, size=None, n=1)


@pytest.mark.asyncio
async def test_openai_generate_and_edit_decode_b64():
    client = MagicMock()
    item = MagicMock()
    item.b64_json = base64.b64encode(_PNG).decode()
    item.url = None
    resp = MagicMock()
    resp.data = [item]
    client.images.generate = AsyncMock(return_value=resp)
    client.images.edit = AsyncMock(return_value=resp)
    proto = OpenAIImageProtocol()
    with patch.object(proto, "_client", return_value=client):
        g = await proto.generate(_provider("openai-image"), _model(), prompt="p", size="1024x1024", n=1)
        e = await proto.edit(_provider("openai-image"), _model(), image=_PNG, prompt="p", mask=None, size=None, n=1)
    assert g.images == [_PNG] and e.images == [_PNG]


def test_get_image_protocol_unknown_raises():
    with pytest.raises(ValueError):
        get_image_protocol("nope")
