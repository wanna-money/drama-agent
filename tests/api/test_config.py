"""模型下拉端点携带 is_default(前端预选默认模型)。"""
import pytest
from unittest.mock import patch, MagicMock

from drama_agent.provider.base import Model, Provider


def _reg_with(models):
    reg = MagicMock()
    reg.models.return_value = models
    reg.get_provider.side_effect = lambda pid: Provider(id=pid, label="L", protocol="openai-compat")
    return reg


@pytest.mark.asyncio
async def test_list_models_carries_is_default():
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    models = [
        Model(id="a", label="A", provider="p", kind="llm"),
        Model(id="b", label="B", provider="p", kind="llm", is_default=True),
    ]
    with patch.object(pp, "provider_registry", _reg_with(models)):
        out = await config_api.list_models()
    by_id = {m["value"]: m for m in out["models"]}
    assert by_id["b"]["is_default"] is True
    assert by_id["a"]["is_default"] is False


@pytest.mark.asyncio
async def test_video_models_carry_is_default():
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    models = [
        Model(id="v1", label="V1", provider="p", kind="video"),
        Model(id="v2", label="V2", provider="p", kind="video", is_default=True),
    ]
    with patch.object(pp, "provider_registry", _reg_with(models)):
        out = await config_api.list_video_models()
    by_id = {m["value"]: m for m in out["models"]}
    assert by_id["v2"]["is_default"] is True
    assert by_id["v1"]["is_default"] is False


@pytest.mark.asyncio
async def test_image_models_value_composite_carries_is_default_and_resolutions():
    """image 项:value 为 provider/id 复合(消歧重复 id)、透传 resolutions/default_resolution、带 is_default。"""
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    models = [
        Model(id="i1", label="I1", provider="p", kind="image"),
        Model(id="i2", label="I2", provider="p", kind="image", is_default=True,
              resolutions=["1024x1024", "1536x1024"], default_resolution="1024x1024"),
    ]
    with patch.object(pp, "provider_registry", _reg_with(models)):
        out = await config_api.list_image_models()
    by_val = {m["value"]: m for m in out["models"]}
    assert set(by_val) == {"p/i1", "p/i2"}                       # value = provider/id 复合
    assert by_val["p/i2"]["is_default"] is True
    assert by_val["p/i2"]["resolutions"] == ["1024x1024", "1536x1024"]
    assert by_val["p/i2"]["default_resolution"] == "1024x1024"


@pytest.mark.asyncio
async def test_list_models_includes_default():
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    models = [
        Model(id="a", label="A", provider="p", kind="llm"),
        Model(id="b", label="B", provider="p", kind="llm", is_default=True),
    ]
    reg = _reg_with(models)
    reg.effective_default.return_value = models[1]
    with patch.object(pp, "provider_registry", reg):
        out = await config_api.list_models()
    assert out["default"] == "b"
    assert isinstance(out["models"], list)


@pytest.mark.asyncio
async def test_list_models_default_none_when_no_effective():
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    reg = _reg_with([])
    reg.effective_default.return_value = None
    with patch.object(pp, "provider_registry", reg):
        out = await config_api.list_models()
    assert out["default"] is None


@pytest.mark.asyncio
async def test_video_and_image_models_include_default():
    import drama_agent.provider as pp
    from drama_agent.api import config_api
    v = Model(id="v2", label="V2", provider="p", kind="video", is_default=True)
    reg = _reg_with([v])
    reg.effective_default.return_value = v
    with patch.object(pp, "provider_registry", reg):
        out_v = await config_api.list_video_models()
    assert out_v["default"] == "v2"

    i = Model(id="i2", label="I2", provider="p", kind="image", is_default=True)
    reg = _reg_with([i])
    reg.effective_default.return_value = i
    with patch.object(pp, "provider_registry", reg):
        out_i = await config_api.list_image_models()
    assert out_i["default"] == "p/i2"          # image default 也是 provider/id 复合
