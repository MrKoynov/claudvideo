import os
import re
import shutil
import subprocess

import pytest

from claudvideo import hyperframes, tts
from claudvideo.cli import pick_engine
from claudvideo.timeline import build_timeline
from tests.conftest import make_script


def svg_with(body: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1150">{body}</svg>'


def timeline_for(script):
    return build_timeline(tts.synthesize(script, None, silent=True))


TWO_BEATS = svg_with(
    '<circle id="c" cx="300" cy="300" r="80" fill="#38BDF8" data-beat="1" data-anim="pop" data-loop="pulse"/>'
    '<path id="p" d="M100 600 L900 600" stroke="#fff" stroke-width="8" fill="none" data-beat="0" data-anim="draw"/>'
    '<text x="540" y="900" font-size="60" text-anchor="middle">база</text>')


def test_scenes_and_subtitles_become_timed_clips():
    script = make_script([TWO_BEATS, TWO_BEATS], beats=[["Раз.", "Два."], ["Три."]])
    tl = timeline_for(script)
    html = hyperframes.build_html(script, tl)

    assert f'data-duration="{tl.total:.3f}"' in html  # длина ролика на корне
    s1 = re.search(r'id="scene-1" class="scene clip" data-start="([\d.]+)" data-duration="([\d.]+)"', html)
    assert float(s1.group(1)) == pytest.approx(tl.scenes[1].start, abs=1e-3)
    assert float(s1.group(1)) + float(s1.group(2)) == pytest.approx(tl.total, abs=1e-3)

    subs = hyperframes.subtitles(tl)
    assert len(subs) == 3
    assert subs[0]["end"] == pytest.approx(subs[1]["start"])  # фраза висит до следующей
    assert subs[-1]["end"] == pytest.approx(tl.total)
    assert html.count('class="sub clip"') == 3
    assert '<audio id="voice" src="voice.wav"' in html


def test_html_escapes_title_and_subtitle_text():
    script = make_script(beats=[["<b>жирный</b> & текст"]])
    script.title = "</script><b>x"
    html = hyperframes.build_html(script, timeline_for(script))
    assert "</script><b>" not in html.split("window.TL")[1].split("</script>")[0]
    assert "&lt;b&gt;жирный&lt;/b&gt;" in html


def test_project_contains_page_gsap_and_audio(tmp_path):
    script = make_script()
    tl = timeline_for(script)
    wav = tmp_path / "mix.wav"
    wav.write_bytes(b"RIFF")
    proj = hyperframes.build_project(script, tl, wav, tmp_path / "proj")
    assert {p.name for p in proj.iterdir()} >= {"index.html", "gsap.min.js", "voice.wav", "package.json"}
    assert hyperframes.HF_VERSION in (proj / "package.json").read_text()


def test_engine_auto_falls_back_without_node(monkeypatch):
    monkeypatch.setattr(hyperframes, "available", lambda: False)
    assert pick_engine("auto") == "builtin"
    monkeypatch.setattr(hyperframes, "available", lambda: True)
    assert pick_engine("auto") == "hyperframes"
    assert pick_engine("builtin") == "builtin"


@pytest.mark.usefixtures("need_chromium")
def test_timeline_reveals_elements_on_their_beat(tmp_path):
    """Страница проекта в Chromium: GSAP-таймлайн прячет элемент до его реплики и показывает после."""
    from playwright.sync_api import sync_playwright

    script = make_script([TWO_BEATS], beats=[["Раз.", "Два."]])
    tl = timeline_for(script)
    wav = tmp_path / "mix.wav"
    wav.write_bytes(b"")
    proj = hyperframes.build_project(script, tl, wav, tmp_path / "proj")
    b0, b1 = tl.scenes[0].beats

    with sync_playwright() as p:
        kw = {}
        if os.environ.get("CLAUDVIDEO_CHROMIUM"):
            kw["executable_path"] = os.environ["CLAUDVIDEO_CHROMIUM"]
        browser = p.chromium.launch(**kw)
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.add_init_script("window.__timelines = {};")  # реестр создаёт рантайм HyperFrames
        page.goto((proj / "index.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.__timelines.claudvideo")

        def at(t, js):
            # seek() возвращает сам таймлайн: не отдаём его в Python, иначе сериализация зависнет
            page.evaluate("t => { window.__timelines.claudvideo.seek(t, false); }", t)
            return page.evaluate(js)

        circle = "() => +getComputedStyle(document.querySelector('#c').parentNode.parentNode).opacity"
        dash = "() => parseFloat(getComputedStyle(document.querySelector('#p')).strokeDashoffset)"
        assert at(b0.start + 0.2, circle) == 0, "до своей реплики элемент скрыт"
        assert at(b1.start + 1.0, circle) == 1
        assert at(b0.start + 0.1, dash) > 100, "линия ещё не прорисована"
        assert at(b0.start + 1.5, dash) == pytest.approx(0, abs=1)
        browser.close()


@pytest.mark.skipif(not (os.environ.get("CLAUDVIDEO_HF_TESTS") and shutil.which("npx")),
                    reason="медленный тест с CLI HyperFrames: CLAUDVIDEO_HF_TESTS=1")
def test_project_passes_hyperframes_check(tmp_path):
    script = make_script()
    tl = timeline_for(script)
    wav = tmp_path / "mix.wav"
    from claudvideo.audio import mix_track, write_wav
    write_wav(mix_track(tts.synthesize(script, None, silent=True), tl), wav)
    proj = hyperframes.build_project(script, tl, wav, tmp_path / "proj")
    res = subprocess.run(["npx", "--yes", f"hyperframes@{hyperframes.HF_VERSION}", "check"],
                         cwd=proj, capture_output=True, text=True, timeout=600)
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-3000:]
