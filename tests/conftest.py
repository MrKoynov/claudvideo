import os
import shutil
import subprocess
from pathlib import Path

import pytest

from claudvideo.models import Scene, Script

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "octopus.json"

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1150">'
    '<circle cx="540" cy="500" r="200" fill="#1A2556" stroke="#38BDF8" stroke-width="8" data-beat="0"/>'
    '<text x="540" y="900" font-size="80" fill="#F4F6FF" text-anchor="middle" font-weight="800" data-beat="0">Привет</text>'
    "</svg>"
)


def make_script(svgs=None, beats=None) -> Script:
    svgs = svgs or [GOOD_SVG]
    beats = beats or [["Первая реплика."]] * len(svgs)
    return Script(
        title="Тест", youtube_title="Тест #shorts", description="d", hashtags=["#a"],
        scenes=[Scene(beats=b, svg=s) for b, s in zip(beats, svgs)], fact_check=[],
    )


def make_tone(path: Path, seconds: float = 0.6) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libmp3lame", str(path)], check=True)
    return path


needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="нужен ffmpeg"
)


@pytest.fixture(scope="session")
def chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            kw = {}
            if os.environ.get("CLAUDVIDEO_CHROMIUM"):
                kw["executable_path"] = os.environ["CLAUDVIDEO_CHROMIUM"]
            p.chromium.launch(**kw).close()
        return True
    except Exception:
        return False


@pytest.fixture
def need_chromium(chromium_ok):
    if not chromium_ok:
        pytest.skip("Chromium недоступен (playwright install chromium)")
