import pytest
from unittest.mock import MagicMock, patch

from drama_agent.services import audio_validate as av


def _mut(length):
    m = MagicMock()
    m.info.length = length
    return m


def test_valid_audio_passes():
    with patch("mutagen.File", return_value=_mut(5.0)):
        av.validate_audio(b"x" * 100, "sample.wav", "audio/wav")


def test_reject_bad_extension():
    with pytest.raises(ValueError, match="wav/mp3"):
        av.validate_audio(b"x", "sample.aac", "audio/aac")


def test_reject_oversize():
    big = b"x" * (15 * 1024 * 1024 + 1)
    with patch("mutagen.File", return_value=_mut(5.0)):
        with pytest.raises(ValueError, match="15MB"):
            av.validate_audio(big, "a.wav", "audio/wav")


@pytest.mark.parametrize("dur", [1.5, 15.5])
def test_reject_duration_out_of_range(dur):
    with patch("mutagen.File", return_value=_mut(dur)):
        with pytest.raises(ValueError, match="2.*15"):
            av.validate_audio(b"x" * 100, "a.wav", "audio/wav")


def test_reject_unrecognized_audio():
    with patch("mutagen.File", return_value=None):
        with pytest.raises(ValueError, match="识别"):
            av.validate_audio(b"x" * 100, "a.wav", "audio/wav")


def test_audio_mime_by_ext():
    assert av.audio_mime("abc.wav") == "audio/wav"
    assert av.audio_mime("abc.mp3") == "audio/mpeg"
