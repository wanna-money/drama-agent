"""Task5 tests: /config/models 与 /video-models 从 registry 派生 + ?available 过滤。"""
import pytest
from httpx import AsyncClient, ASGITransport

from drama_agent.provider.base import Model, Provider
from drama_agent.provider.registry import ProviderRegistry


@pytest.fixture
async def client(monkeypatch):
    # 用受控 registry 替换模块级单例(动态查点在 api.config_api 里引用 provider_pkg)
    import drama_agent.provider as provider_pkg
    reg = ProviderRegistry(builtin=[
        Provider(id="kimi", label="Kimi", protocol="openai-compat",
                 api_key="sk-have",  # 明文 → resolve_credential 原样返回 → available
                 models=[Model(id="k2", label="Kimi K2", provider="kimi", kind="llm")]),
        Provider(id="drama", label="DeepSeek", protocol="openai-compat",
                 api_key=None,  # 未配 → 不进 available
                 models=[Model(id="ds", label="DeepSeek", provider="drama", kind="llm")]),
        Provider(id="minimax-video", label="MiniMax", protocol="minimax",
                 models=[Model(id="minimax", label="MiniMax H3", provider="minimax-video",
                               kind="video", resolutions=["768P", "2K"], default_resolution="768P")]),
        Provider(id="doubao-image", label="豆包 Seedream", protocol="doubao-image",
                 api_key="sk-have",
                 models=[Model(id="sd", label="Seedream", provider="doubao-image", kind="image")]),
    ], custom_providers=[])
    monkeypatch.setattr(provider_pkg, "provider_registry", reg)
    from drama_agent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_models_derived_from_registry(client):
    r = await client.get("/api/config/models")
    assert r.status_code == 200
    models = r.json()["models"]
    values = {m["value"] for m in models}
    assert values == {"k2", "ds"}                      # 只 LLM
    k2 = next(m for m in models if m["value"] == "k2")
    assert k2["label"] == "Kimi K2" and k2["provider"] == "Kimi"


@pytest.mark.asyncio
async def test_video_models_carry_resolutions(client):
    r = await client.get("/api/config/video-models")
    models = r.json()["models"]
    assert {m["value"] for m in models} == {"minimax"}  # 只 video
    mm = models[0]
    assert mm["resolutions"] == ["768P", "2K"]
    assert mm["default_resolution"] == "768P"


@pytest.mark.asyncio
async def test_available_filter_excludes_unconfigured(client):
    r = await client.get("/api/config/models?available=true")
    values = {m["value"] for m in r.json()["models"]}
    assert values == {"k2"}                             # drama 未配凭证被排除


@pytest.mark.asyncio
async def test_image_models_endpoint(client):
    r = await client.get("/api/config/image-models")
    assert r.status_code == 200
    # image value 为 provider/id 复合(消歧同名 model id,如多个 gpt-image-2)
    assert {m["value"] for m in r.json()["models"]} == {"doubao-image/sd"}
