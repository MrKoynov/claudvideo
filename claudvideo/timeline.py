"""Расчёт времени: когда звучит каждая реплика, слово, и когда начинается сцена."""

from __future__ import annotations

from dataclasses import dataclass, field

LEAD_IN = 0.35     # тишина в начале
BEAT_GAP = 0.12    # пауза между репликами одной сцены
SCENE_GAP = 0.40   # пауза между сценами
TAIL = 0.90        # тишина в конце


@dataclass
class Word:
    text: str
    start: float  # секунды от начала реплики
    end: float


@dataclass
class BeatAudio:
    """Озвучка одной реплики."""
    text: str
    duration: float
    words: list[Word]
    path: str | None = None  # mp3; None в беззвучном режиме


@dataclass
class BeatTiming:
    text: str
    start: float
    end: float
    words: list[Word]  # время абсолютное, от начала ролика


@dataclass
class SceneTiming:
    start: float
    end: float
    beats: list[BeatTiming] = field(default_factory=list)


@dataclass
class Timeline:
    scenes: list[SceneTiming]
    total: float


def proportional_words(text: str, duration: float) -> list[Word]:
    """Раскидать слова по длительности пропорционально их длине.

    Запасной вариант, когда TTS не отдал границы слов. Для коротких реплик
    ошибка не больше доли секунды.
    """
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t.strip(".,!?;:—-«»\"'()")) + 1.5 for t in tokens]
    total = sum(weights)
    words, t = [], 0.0
    for tok, w in zip(tokens, weights):
        span = duration * w / total
        words.append(Word(tok, t, t + span))
        t += span
    return words


def build_timeline(audio: list[list[BeatAudio]]) -> Timeline:
    """audio[i][j] - озвучка реплики j сцены i."""
    scenes: list[SceneTiming] = []
    t = LEAD_IN
    for i, scene_audio in enumerate(audio):
        beats: list[BeatTiming] = []
        for j, a in enumerate(scene_audio):
            start = t
            end = start + a.duration
            words = [Word(w.text, start + w.start, start + w.end) for w in a.words]
            beats.append(BeatTiming(a.text, start, end, words))
            t = end + (BEAT_GAP if j < len(scene_audio) - 1 else 0.0)
        scenes.append(SceneTiming(0.0, 0.0, beats))
        t += SCENE_GAP

    total = (scenes[-1].beats[-1].end if scenes and scenes[-1].beats else LEAD_IN) + TAIL

    # Граница сцен - середина паузы между ними: картинка чуть опережает голос.
    for i, sc in enumerate(scenes):
        sc.start = 0.0 if i == 0 else sc.beats[0].start - SCENE_GAP / 2
        sc.end = total if i == len(scenes) - 1 else scenes[i + 1].beats[0].start - SCENE_GAP / 2
    return Timeline(scenes, total)
