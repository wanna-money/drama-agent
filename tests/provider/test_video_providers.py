"""Task4 tests: video provider 接入统一 registry(model 级 supported_actions/resolutions)。"""
import pytest
from drama_agent.provider.video.providers import builtin_video_providers
from drama_agent.provider.registry import ProviderRegistry


def _video_registry():
    return ProviderRegistry(builtin=builtin_video_providers(), custom_providers=[])


def test_video_providers_registered_with_video_kind():
    reg = _video_registry()
    ids = {m.id for m in reg.models(kind="video")}
    assert ids == {"seedance", "seedance-2.5", "minimax"}


def test_video_model_carries_resolutions():
    reg = _video_registry()
    _, minimax = reg.resolve_model("minimax")
    assert minimax.resolutions == ["768P", "2K"]
    assert minimax.default_resolution == "768P"


def test_video_model_carries_supported_actions_at_model_grain():
    """supported_actions 迁到 model 粒度:minimax 有 upscale,seedance 没有。"""
    reg = _video_registry()
    _, minimax = reg.resolve_model("minimax")
    _, seedance = reg.resolve_model("seedance")
    assert set(minimax.supported_actions) == {"rerun", "regenerate", "upscale"}
    assert "upscale" not in seedance.supported_actions


def test_video_resolve_unknown_raises():
    reg = _video_registry()
    with pytest.raises(ValueError):
        reg.resolve_model("no-such-video-model")


def test_video_models_declare_audio_capability_and_default():
    from drama_agent.provider.video.providers import builtin_video_providers
    models = {m.id: m for p in builtin_video_providers() for m in p.models}
    assert models["seedance"].supports_audio_reference is True
    assert models["seedance-2.5"].supports_audio_reference is True
    assert models["minimax"].supports_audio_reference is True
    assert models["seedance"].max_reference_audios == 3
    assert models["seedance-2.5"].max_reference_audios == 10
    assert models["minimax"].max_reference_audios == 3
    assert models["seedance"].is_default is True
    assert models["seedance-2.5"].is_default is False
    assert models["minimax"].is_default is False
    prov_of = {m.id: p for p in builtin_video_providers() for m in p.models}
    assert prov_of["seedance-2.5"].id == "seedance-video"
    assert prov_of["seedance-2.5"].protocol == "seedance"
