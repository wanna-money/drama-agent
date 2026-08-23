from drama_agent.config import settings
from drama_agent.provider.video.providers import builtin_video_providers


def test_minimax_video_settings_exist():
    assert hasattr(settings, "minimax_video_api_key")
    assert settings.minimax_video_base_url == "https://api.minimaxi.com"


def _video_models():
    return [m for p in builtin_video_providers() for m in p.models]


def test_video_models_include_minimax_with_resolutions():
    # 分辨率真相迁到 provider registry(model 粒度),不再在 settings.video_models
    models = _video_models()
    values = {m.id for m in models}
    assert "minimax" in values
    minimax = next(m for m in models if m.id == "minimax")
    assert minimax.resolutions == ["768P", "2K"]
    assert minimax.default_resolution == "768P"


def test_all_video_models_have_resolution_fields():
    for m in _video_models():
        assert m.resolutions, f"{m.id} missing resolutions"
        assert m.default_resolution in m.resolutions
