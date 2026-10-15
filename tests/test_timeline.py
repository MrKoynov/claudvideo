import pytest

from claudvideo.timeline import (BEAT_GAP, LEAD_IN, SCENE_GAP, TAIL, BeatAudio, Word,
                                 build_timeline, proportional_words)


def beat(text, dur):
    return BeatAudio(text, dur, proportional_words(text, dur))


def test_proportional_words_cover_duration_monotonically():
    words = proportional_words("Два сердца гонят кровь через жабры", 3.0)
    assert [w.text for w in words] == "Два сердца гонят кровь через жабры".split()
    assert words[0].start == 0
    assert words[-1].end == pytest.approx(3.0)
    assert all(a.end == pytest.approx(b.start) for a, b in zip(words, words[1:]))


def test_proportional_words_empty():
    assert proportional_words("   ", 1.0) == []


def test_timeline_offsets():
    audio = [[beat("а б", 2.0), beat("в г", 1.0)], [beat("д", 1.5)]]
    tl = build_timeline(audio)
    b00, b01 = tl.scenes[0].beats
    b10 = tl.scenes[1].beats[0]
    assert b00.start == pytest.approx(LEAD_IN)
    assert b01.start == pytest.approx(LEAD_IN + 2.0 + BEAT_GAP)
    assert b10.start == pytest.approx(b01.end + SCENE_GAP)
    assert tl.total == pytest.approx(b10.end + TAIL)


def test_scene_boundaries_are_contiguous_and_cover_video():
    audio = [[beat("а", 1.0)], [beat("б", 1.0)], [beat("в", 1.0)]]
    tl = build_timeline(audio)
    assert tl.scenes[0].start == 0
    for a, b in zip(tl.scenes, tl.scenes[1:]):
        assert a.end == pytest.approx(b.start)
        assert b.start == pytest.approx(b.beats[0].start - SCENE_GAP / 2)
    assert tl.scenes[-1].end == pytest.approx(tl.total)


def test_word_times_are_absolute():
    a = BeatAudio("раз два", 2.0, [Word("раз", 0.0, 1.0), Word("два", 1.0, 2.0)])
    tl = build_timeline([[a]])
    w = tl.scenes[0].beats[0].words
    assert w[0].start == pytest.approx(LEAD_IN)
    assert w[1].start == pytest.approx(LEAD_IN + 1.0)
