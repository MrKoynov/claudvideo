"""Озвучка реплик через edge-tts (бесплатные нейроголоса Microsoft).

Каждая реплика синтезируется отдельно: так мы точно знаем, когда она звучит,
и привязываем к ней появление элементов схемы. Результаты кэшируются по тексту,
голосу и скорости, поэтому повторный рендер после правки одной сцены не
синтезирует остальное заново.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from pathlib import Path

from .models import Script
from .timeline import BeatAudio, Word, proportional_words

DEFAULT_VOICE = "ru-RU-DmitryNeural"  # женский вариант: ru-RU-SvetlanaNeural
SILENT_CHARS_PER_SEC = 14.0  # грубая оценка скорости русской речи


def estimate_duration(text: str, rate_pct: int = 0) -> float:
    return max(1.0, len(text) / (SILENT_CHARS_PER_SEC * (1 + rate_pct / 100)))


def parse_rate(rate: str) -> int:
    """'+10%' -> 10; нужно только для беззвучной оценки длительности."""
    try:
        return int(rate.replace("%", "").replace("+", ""))
    except ValueError:
        return 0


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip())


def _cache_key(text: str, voice: str, rate: str) -> str:
    return hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]


def words_from_boundaries(text: str, events: list[dict], duration: float) -> list[Word]:
    """Слова с границами от TTS, если число слов совпало; иначе пропорционально."""
    tokens = text.split()
    if events and len(events) == len(tokens):
        return [
            Word(tok, ev["offset"] / 1e7, min(duration, (ev["offset"] + ev["duration"]) / 1e7))
            for tok, ev in zip(tokens, events)
        ]
    return proportional_words(text, duration)


async def _synth_one(text: str, voice: str, rate: str, mp3: Path, meta: Path) -> None:
    import edge_tts

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
            audio = bytearray()
            events: list[dict] = []
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    audio += chunk["data"]
                elif chunk["type"] == "WordBoundary":
                    events.append({"offset": chunk["offset"], "duration": chunk["duration"],
                                   "text": chunk["text"]})
            if not audio:
                raise RuntimeError("TTS вернул пустое аудио")
            mp3.write_bytes(bytes(audio))
            meta.write_text(json.dumps(events), encoding="utf-8")
            return
        except Exception as e:  # сеть у edge-tts капризная
            last_err = e
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"edge-tts не смог озвучить «{text[:40]}…»: {last_err}")


async def _synth_all(script: Script, workdir: Path, voice: str, rate: str) -> None:
    sem = asyncio.Semaphore(4)

    async def job(text: str) -> None:
        key = _cache_key(text, voice, rate)
        mp3, meta = workdir / f"{key}.mp3", workdir / f"{key}.json"
        if mp3.exists() and meta.exists():
            return
        async with sem:
            await _synth_one(text, voice, rate, mp3, meta)

    texts = list(dict.fromkeys(b for s in script.scenes for b in s.beats))
    await asyncio.gather(*(job(t) for t in texts))


def synthesize(script: Script, workdir: Path | None, voice: str = DEFAULT_VOICE,
               rate: str = "+0%", silent: bool = False) -> list[list[BeatAudio]]:
    """Озвучить все реплики. В беззвучном режиме длительность оценивается по тексту."""
    if silent:
        pct = parse_rate(rate)
        out = []
        for s in script.scenes:
            row = []
            for b in s.beats:
                d = estimate_duration(b, pct)
                row.append(BeatAudio(b, d, proportional_words(b, d), None))
            out.append(row)
        return out

    workdir.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synth_all(script, workdir, voice, rate))
    out = []
    for s in script.scenes:
        row = []
        for b in s.beats:
            key = _cache_key(b, voice, rate)
            mp3 = workdir / f"{key}.mp3"
            events = json.loads((workdir / f"{key}.json").read_text(encoding="utf-8"))
            dur = probe_duration(mp3)
            row.append(BeatAudio(b, dur, words_from_boundaries(b, events, dur), str(mp3)))
        out.append(row)
    return out
