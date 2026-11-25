from types import SimpleNamespace as NS

import pytest

from reels.alignment.captions import group_captions, validate_caption_sync
from reels.alignment.retime import retime_beats


def W(text, s, e):
    return NS(text=text, start=s, end=e)


def test_captions_break_on_sentence_end_and_limits():
    words = [W("AI", 0, .3), W("tumhari", .3, .7), W("line", .7, 1.0), W("padhta", 1.0, 1.4), W("hi", 1.4, 1.5),
             W("nahi", 1.5, 1.8), W("hai.", 1.8, 2.1), W("Wo", 2.5, 2.7), W("sirf", 2.7, 3.0)]
    segs = group_captions(words)
    assert all(len(s.words) <= 4 for s in segs)
    assert segs[1].words[-1].text == "hai."              # sentence end closes a segment
    assert segs[2].words[0].text == "Wo"                 # pause > 0.35 s starts a new segment
    assert validate_caption_sync(segs, words)["passed"]


def test_caption_sync_detects_missing_words():
    words = [W("a", 0, .2), W("b", .2, .4)]
    segs = group_captions(words)
    assert not validate_caption_sync(segs, words[:1])["passed"]


def test_retime_uses_audio_as_clock():
    beats = [NS(id="b01", narration="ek do teen"), NS(id="b02", narration="chaar paanch")]
    words = [W("ek", 0, .4), W("do", .4, .8), W("teen", .8, 1.2), W("chaar", 1.6, 2.0), W("paanch", 2.0, 2.6)]
    out = retime_beats(beats, words, audio_duration=2.6)
    assert out[0] == ("b01", 0.0, 1.2)
    assert out[1][1] == 1.2 and out[1][2] == pytest.approx(2.85)   # contiguous, tail padded


def test_retime_refuses_word_count_mismatch():
    beats = [NS(id="b01", narration="ek do teen chaar")]
    with pytest.raises(ValueError):
        retime_beats(beats, [W("ek", 0, .3)], audio_duration=1)
