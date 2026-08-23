import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _fake_provider_model(protocol="doubao-image"):
    provider = MagicMock()
    provider.protocol = protocol
    model = MagicMock()
    return provider, model


def _fake_proto(images=None, edit_exc=None):
    from drama_agent.provider.image.protocols import ImageResult
    proto = MagicMock()
    proto.generate = AsyncMock(return_value=ImageResult(images=images or [b"PNGBYTES"]))
    if edit_exc is not None:
        proto.edit = AsyncMock(side_effect=edit_exc)
    else:
        proto.edit = AsyncMock(return_value=ImageResult(images=images or [b"EDITED"]))
    return proto


@pytest.mark.asyncio
async def test_generate_image_resolves_and_passes_prompt_size():
    from drama_agent.services import asset_gen_service
    import drama_agent.provider as provider_pkg
    proto = _fake_proto(images=[b"PNGBYTES"])
    reg = MagicMock()
    reg.resolve_model = MagicMock(return_value=_fake_provider_model())
    with patch.object(provider_pkg, "provider_registry", reg), \
         patch("drama_agent.services.asset_gen_service.get_image_protocol", return_value=proto):
        out = await asset_gen_service.generate_image(
            "doubao-seedream-3-0-t2i", "a hero", size="1024x1024", n=1
        )
    assert out == [b"PNGBYTES"]
    reg.resolve_model.assert_called_once_with("doubao-seedream-3-0-t2i")
    kwargs = proto.generate.call_args.kwargs
    assert kwargs["size"] == "1024x1024"
    assert kwargs["n"] == 1
    assert proto.generate.call_args.args[2] == "a hero"  # (provider, model, prompt, ...)


@pytest.mark.asyncio
async def test_generate_image_unknown_model_raises_valueerror():
    from drama_agent.services import asset_gen_service
    import drama_agent.provider as provider_pkg
    reg = MagicMock()
    reg.resolve_model = MagicMock(side_effect=ValueError("Unknown model"))
    with patch.object(provider_pkg, "provider_registry", reg):
        with pytest.raises(ValueError):
            await asset_gen_service.generate_image("nope", "x")


@pytest.mark.asyncio
async def test_edit_image_reads_source_and_passes_bytes():
    from drama_agent.services import asset_gen_service
    import drama_agent.provider as provider_pkg
    proto = _fake_proto(images=[b"EDITED"])
    reg = MagicMock()
    reg.resolve_model = MagicMock(return_value=_fake_provider_model())
    with patch.object(provider_pkg, "provider_registry", reg), \
         patch("drama_agent.services.asset_gen_service.get_image_protocol", return_value=proto), \
         patch("drama_agent.services.asset_service.read_asset_bytes",
               AsyncMock(return_value=b"SRC")):
        out = await asset_gen_service.edit_image(
            "a1", "gpt-image-2", "make it night", size=None, n=1
        )
    assert out == [b"EDITED"]
    assert proto.edit.call_args.args[2] == b"SRC"       # (provider, model, image, prompt, ...)
    assert proto.edit.call_args.args[3] == "make it night"
    assert proto.edit.call_args.kwargs["mask"] is None


@pytest.mark.asyncio
async def test_edit_image_missing_asset_raises_lookuperror():
    from drama_agent.services import asset_gen_service
    with patch("drama_agent.services.asset_service.read_asset_bytes",
               AsyncMock(return_value=None)):
        with pytest.raises(LookupError):
            await asset_gen_service.edit_image("gone", "gpt-image-2", "x")


@pytest.mark.asyncio
async def test_edit_image_propagates_notimplemented():
    from drama_agent.services import asset_gen_service
    import drama_agent.provider as provider_pkg
    proto = _fake_proto(edit_exc=NotImplementedError("Seedream 不支持编辑"))
    reg = MagicMock()
    reg.resolve_model = MagicMock(return_value=_fake_provider_model())
    with patch.object(provider_pkg, "provider_registry", reg), \
         patch("drama_agent.services.asset_gen_service.get_image_protocol", return_value=proto), \
         patch("drama_agent.services.asset_service.read_asset_bytes",
               AsyncMock(return_value=b"SRC")):
        with pytest.raises(NotImplementedError):
            await asset_gen_service.edit_image("a1", "doubao-seedream-3-0-t2i", "x")
