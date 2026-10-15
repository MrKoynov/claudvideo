import subprocess

import numpy as np
import pytest

from claudvideo import tts
from claudvideo.audio import SR, mix_track
from claudvideo.timeline import BeatAudio, build_timeline, proportional_words
from tests.conftest import make_script, make_tone, needs_ffmpeg


def test_words_from_boundaries_uses_events_when_counts_match():
    events = [{"offset": 0, "duration": 5_000_000, "text": "раз"},
              {"offset": 5_000_000, "duration": 5_000_000, "text": "два"}]
    w = tts.words_from_boundaries("раз два", events, duration=1.0)
    assert [(x.text, x.start, x.end) for x in w] == [("раз", 0.0, 0.5), ("два", 0.5, 1.0)]


def test_words_from_boundaries_falls_back_when_counts_differ():
    events = [{"offset": 0, "duration": 5_000_000, "text": "раздва"}]
    w = tts.words_from_boundaries("раз два", events, duration=1.0)
    assert len(w) == 2 and w[-1].end == pytest.approx(1.0)


def test_words_from_boundaries_without_events():
    w = tts.words_from_boundaries("раз два", [], duration=2.0)
    assert len(w) == 2


def test_estimate_duration_scales_with_rate():
    assert tts.estimate_duration("а" * 140) == pytest.approx(10.0)
    assert tts.estimate_duration("а" * 140, 50) < tts.estimate_duration("а" * 140)
    assert tts.estimate_duration("а") == 1.0  # нижняя граница


def test_parse_rate():
    assert tts.parse_rate("+10%") == 10 and tts.parse_rate("-5%") == -5 and tts.parse_rate("x") == 0


def test_silent_synthesize_needs_no_workdir():
    s = make_script(beats=[["Одна реплика.", "Вторая реплика, подлиннее."]])
    audio = tts.synthesize(s, None, silent=True)
    assert [len(r) for r in audio] == [2]
    assert audio[0][1].duration > audio[0][0].duration
    assert audio[0][0].path is None


@needs_ffmpeg
def test_synthesize_with_cache(tmp_path, monkeypatch):
    """Путь с реальным файлом: подменяем только сетевой вызов edge-tts."""
    calls = []

    async def fake(text, voice, rate, mp3, meta):
        calls.append(text)
        make_tone(mp3, 0.6)
        meta.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(tts, "_synth_one", fake)
    s = make_script(beats=[["Раз два.", "Три четыре."]])
    a1 = tts.synthesize(s, tmp_path)
    assert sorted(calls) == ["Раз два.", "Три четыре."]
    assert a1[0][0].duration == pytest.approx(0.6, abs=0.1)
    assert len(a1[0][0].words) == 2

    tts.synthesize(s, tmp_path)
    assert len(calls) == 2, "повторный запуск должен брать озвучку из кэша"

    tts.synthesize(s, tmp_path, rate="+10%")
    assert len(calls) == 4, "другая скорость значит новый синтез"


@needs_ffmpeg
def test_mix_places_voice_at_timeline_offsets(tmp_path):
    tone = make_tone(tmp_path / "t.mp3", 0.5)
    a = BeatAudio("раз", 0.5, proportional_words("раз", 0.5), str(tone))
    tl = build_timeline([[a]])
    pcm = mix_track([[a]], tl)
    assert len(pcm) == int(round(tl.total * SR))
    start = int(tl.scenes[0].beats[0].start * SR)
    loud = np.abs(pcm[start + 2000 : start + 20000]).mean()
    quiet = np.abs(pcm[: start - 100]).mean()
    assert loud > 500 and quiet == 0


@needs_ffmpeg
def test_music_is_looped_and_mixed_under_voice(tmp_path):
    music = make_tone(tmp_path / "m.mp3", 0.3)
    a = BeatAudio("раз", 0.5, proportional_words("раз", 0.5), None)
    tl = build_timeline([[a]])
    pcm = mix_track([[a]], tl, music=str(music), music_gain=0.2)
    assert len(pcm) == int(round(tl.total * SR))
    mid = np.abs(pcm[SR // 2 : SR]).mean()  # музыка короче ролика, но должна зацикливаться
    assert mid > 100
