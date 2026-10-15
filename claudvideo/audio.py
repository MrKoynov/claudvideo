"""Сборка единой звуковой дорожки: реплики по таймлайну + необязательная музыка."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .timeline import BeatAudio, Timeline

SR = 44100


def decode(path: str) -> np.ndarray:
    """Любой аудиофайл -> int16 стерео 44.1 кГц, форма (n, 2)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ar", str(SR), "-ac", "2", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16).reshape(-1, 2)


def mix_track(audio: list[list[BeatAudio]], tl: Timeline,
              music: str | None = None, music_gain: float = 0.12) -> np.ndarray:
    n = int(round(tl.total * SR))
    mix = np.zeros((n, 2), dtype=np.float32)

    for scene_audio, scene_tl in zip(audio, tl.scenes):
        for a, b in zip(scene_audio, scene_tl.beats):
            if a.path is None:
                continue
            pcm = decode(a.path).astype(np.float32)
            i0 = int(round(b.start * SR))
            seg = pcm[: max(0, n - i0)]
            mix[i0 : i0 + len(seg)] += seg

    if music:
        m = decode(music).astype(np.float32)
        if len(m):
            reps = -(-n // len(m))  # зацикливаем, если музыка короче ролика
            m = np.tile(m, (reps, 1))[:n]
            fade = min(n, int(1.5 * SR))
            m[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
            mix += m * music_gain

    return np.clip(mix, -32768, 32767).astype(np.int16)


def write_wav(pcm: np.ndarray, path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
