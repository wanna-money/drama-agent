from drama_agent.services.video_refs import (
    RefAudio,
    RefImage,
    audio_content_items,
    cap_audio_refs,
    designate_prompt,
)


def test_audio_content_items_shape():
    items = audio_content_items([RefAudio(url="data:audio/wav;base64,AA", subject_name="林夏")])
    assert items == [{"type": "audio_url",
                      "audio_url": {"url": "data:audio/wav;base64,AA"},
                      "role": "reference_audio"}]


def test_cap_audio_refs_truncates():
    auds = [RefAudio(url=f"a{i}") for i in range(5)]
    assert len(cap_audio_refs(auds, 3, "seedance")) == 3
    assert cap_audio_refs(auds, 10, "seedance-2.5") == auds


def test_designate_prompt_appends_audio_designation():
    out = designate_prompt(
        "夜景对话",
        refs=[RefImage(url="u", kind="subject", subject_name="林夏", view="front")],
        audio_refs=[RefAudio(url="a1", subject_name="林夏")],
    )
    assert "参考图1为角色「林夏」正面参考" in out
    assert "使用 @音频1 的音色为角色「林夏」配音" in out


def test_designate_prompt_audio_only():
    out = designate_prompt("独白", refs=[], audio_refs=[RefAudio(url="a1", subject_name="陆沉")])
    assert "使用 @音频1 的音色为角色「陆沉」配音" in out


def test_designate_prompt_no_refs_unchanged():
    assert designate_prompt("原样", refs=[], audio_refs=None) == "原样"
