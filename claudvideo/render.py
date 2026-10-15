"""Рендер: HTML-кадр -> скриншоты Chromium -> ffmpeg -> mp4 1080x1920."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .models import Script
from .timeline import Timeline

W, H = 1080, 1920
TEMPLATE = Path(__file__).with_name("frame.html")


def clean_svg(svg: str) -> str:
    """Убрать то, что ломает встраивание SVG в HTML."""
    svg = re.sub(r"^\s*<\?xml[^>]*\?>", "", svg)
    return re.sub(r"<!--.*?-->", "", svg, flags=re.S).strip()


def build_html(script: Script, tl: Timeline) -> str:
    data = {
        "title": script.title,
        "total": tl.total,
        "scenes": [asdict(s) for s in tl.scenes],
    }
    payload = "window.TL = " + json.dumps(data, ensure_ascii=False).replace("<", "\\u003c") + ";"
    scenes_html = "\n".join(
        f'<div class="scene" id="scene-{i}">{clean_svg(s.svg)}</div>'
        for i, s in enumerate(script.scenes)
    )
    html = TEMPLATE.read_text(encoding="utf-8")
    return html.replace("<!--SCENES-->", scenes_html).replace("/*__DATA__*/", payload)


class FrameRenderer:
    """Держит открытую страницу и по времени t выдаёт кадр."""

    def __init__(self, script: Script, tl: Timeline):
        self.script, self.tl = script, tl
        self.html = build_html(script, tl)

    def __enter__(self) -> "FrameRenderer":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        kwargs = {"args": ["--hide-scrollbars", "--font-render-hinting=none"]}
        if os.environ.get("CLAUDVIDEO_CHROMIUM"):
            kwargs["executable_path"] = os.environ["CLAUDVIDEO_CHROMIUM"]
        try:
            self._browser = self._pw.chromium.launch(**kwargs)
        except Exception as e:
            self._pw.stop()
            raise RuntimeError(
                "Не удалось запустить Chromium. Выполните `playwright install chromium` "
                "или укажите путь к браузеру в переменной CLAUDVIDEO_CHROMIUM.\n" + str(e)
            ) from e
        self.page = self._browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        self.page.set_content(self.html, wait_until="load")
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    def frame(self, t: float, lossless: bool = False) -> bytes:
        """Кадр на момент t. Для видео берём JPEG q95: в 5 раз быстрее PNG, а на выходе всё равно yuv420p."""
        self.page.evaluate("t => window.seek(t)", t)
        if lossless:
            return self.page.screenshot(type="png")
        return self.page.screenshot(type="jpeg", quality=95)

    def settled_time(self, i: int) -> float:
        return self.page.evaluate("i => window.settledTime(i)", i)

    def lint(self) -> dict[int, list[str]]:
        found = {}
        for i in range(len(self.script.scenes)):
            issues = self.page.evaluate("i => window.lintScene(i)", i)
            if issues:
                found[i] = issues
        return found


def render_previews(script: Script, tl: Timeline, out_dir: Path) -> list[Path]:
    """По одному стоп-кадру на сцену (в собранном виде): быстро оценить схемы глазами."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with FrameRenderer(script, tl) as r:
        for i in range(len(script.scenes)):
            p = out_dir / f"scene_{i + 1:02d}.png"
            p.write_bytes(r.frame(r.settled_time(i), lossless=True))
            paths.append(p)
    return paths


def render_video(script: Script, tl: Timeline, wav: Path, out: Path, fps: int = 30,
                 progress: bool = True) -> None:
    n = int(-(-tl.total * fps // 1))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
        "-i", str(wav),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out),
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with FrameRenderer(script, tl) as r:
            for k in range(n):
                ff.stdin.write(r.frame(k / fps))
                if progress and k % 30 == 0:
                    print(f"\rкадр {k}/{n}", end="", file=sys.stderr, flush=True)
        ff.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        ff.kill()
        raise
    err = ff.stderr.read().decode(errors="replace")
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg завершился с ошибкой:\n" + err)
    if progress:
        print(f"\rкадр {n}/{n}  готово", file=sys.stderr)
