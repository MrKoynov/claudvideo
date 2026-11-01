"""Рендер через HyperFrames: script.json -> проект HyperFrames (HTML + GSAP) -> mp4.

Разметка сцен та же, что у встроенного движка (data-beat, data-anim, data-delay, data-loop),
но анимацию ведёт GSAP-таймлайн: мягкие кривые, смена сцен со сдвигом, «всплывающие» субтитры
с подсветкой слова. Рендерит CLI HyperFrames (нужен Node.js 22+, `npx`).
"""

from __future__ import annotations

import html as htmlmod
import json
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from .models import Script
from .render import clean_svg
from .timeline import Timeline

HF_VERSION = "0.8.229"  # версия CLI зафиксирована, чтобы рендер был воспроизводимым
HERE = Path(__file__).parent
TEMPLATE = HERE / "hf_frame.html"
GSAP = HERE / "vendor" / "gsap.min.js"


def available() -> bool:
    return shutil.which("npx") is not None


def subtitles(tl: Timeline) -> list[dict]:
    """Окна субтитров: фраза висит до начала следующей (последняя до конца ролика)."""
    beats = [b for sc in tl.scenes for b in sc.beats]
    out = []
    for i, b in enumerate(beats):
        end = beats[i + 1].start if i + 1 < len(beats) else tl.total
        out.append({"start": round(b.start, 3), "end": round(end, 3),
                    "words": [{"text": w.text, "start": round(w.start, 3)} for w in b.words],
                    "text": b.text})
    return out


def build_html(script: Script, tl: Timeline) -> str:
    subs = subtitles(tl)
    data = {"title": script.title, "total": tl.total,
            "scenes": [asdict(s) for s in tl.scenes], "subs": subs}
    payload = "window.TL = " + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + ";"

    scenes_html = []
    for i, (s, sc) in enumerate(zip(script.scenes, tl.scenes)):
        end = tl.total if i == len(tl.scenes) - 1 else sc.end
        scenes_html.append(
            f'<section id="scene-{i}" class="scene clip" data-start="{sc.start:.3f}" '
            f'data-duration="{end - sc.start:.3f}" data-track-index="1">'
            f'<div class="scene-inner">{clean_svg(s.svg)}</div></section>')

    subs_html = []
    for i, b in enumerate(subs):
        words = "".join(f'<span class="w">{htmlmod.escape(w["text"])}</span>' for w in b["words"])
        cls = "sub-line long" if len(b["text"]) > 64 else "sub-line"
        subs_html.append(
            f'<div id="sub-{i}" class="sub clip" data-start="{b["start"]:.3f}" '
            f'data-duration="{b["end"] - b["start"]:.3f}" data-track-index="2">'
            f'<div class="{cls}">{words}</div></div>')

    page = TEMPLATE.read_text(encoding="utf-8")
    return (page.replace("<!--SCENES-->", "\n".join(scenes_html))
                .replace("<!--SUBS-->", "\n".join(subs_html))
                .replace("/*__TOTAL__*/", f"{tl.total:.3f}")
                .replace("/*__DATA__*/", payload))


def build_project(script: Script, tl: Timeline, wav: Path, project: Path) -> Path:
    """Собрать папку проекта HyperFrames. Её можно открыть в Studio: `npx hyperframes preview`."""
    project.mkdir(parents=True, exist_ok=True)
    (project / "index.html").write_text(build_html(script, tl), encoding="utf-8")
    shutil.copyfile(GSAP, project / "gsap.min.js")
    shutil.copyfile(wav, project / "voice.wav")
    (project / "package.json").write_text(json.dumps({
        "name": "claudvideo-render", "private": True, "type": "module",
        "scripts": {cmd: f"npx --yes hyperframes@{HF_VERSION} {cmd}"
                    for cmd in ("preview", "check", "render")},
    }, indent=2), encoding="utf-8")
    return project


def render_video(script: Script, tl: Timeline, wav: Path, out: Path, project: Path,
                 fps: int = 30, quality: str = "delivery", progress: bool = True) -> None:
    if not available():
        raise RuntimeError("Для движка HyperFrames нужен Node.js 22+ (команда npx). "
                           "Установите Node.js или запустите с --engine builtin.")
    build_project(script, tl, wav, project)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "--yes", f"hyperframes@{HF_VERSION}", "render",
           "--output", str(out.resolve()), "--fps", str(fps), "--quality", quality]
    if not progress:
        cmd.append("--quiet")
    res = subprocess.run(cmd, cwd=project, capture_output=not progress, text=True)
    if res.returncode != 0 or not out.exists():
        tail = (res.stderr or "")[-3000:] if not progress else ""
        raise RuntimeError(f"HyperFrames не смог отрендерить видео (код {res.returncode}). "
                           f"Проект: {project}\n{tail}")
