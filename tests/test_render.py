import json
import subprocess
import struct

import pytest

from claudvideo import tts
from claudvideo.cli import main
from claudvideo.render import FrameRenderer, build_html
from claudvideo.timeline import build_timeline
from claudvideo.models import Script
from tests.conftest import GOOD_SVG, SAMPLE, make_script, make_tone, needs_ffmpeg

pytestmark = pytest.mark.usefixtures("need_chromium")


def svg_with(body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1150">{body}</svg>')


def timeline_for(script):
    return build_timeline(tts.synthesize(script, None, silent=True))


def png_size(data: bytes):
    return struct.unpack(">II", data[16:24])


def lint(*bodies):
    script = make_script([svg_with(b) for b in bodies])
    with FrameRenderer(script, timeline_for(script)) as r:
        return r.lint()


def test_html_survives_script_closing_tag_in_title():
    script = make_script()
    script.title = "</script><b>x"
    html = build_html(script, timeline_for(script))
    assert "</script><b>" not in html.split("window.TL")[1].split("</script>")[0]


def test_elements_appear_on_their_beat():
    script = make_script([svg_with(
        '<circle id="c" cx="100" cy="100" r="50" data-beat="1" data-anim="fade"/>'
        '<text x="540" y="900" font-size="60" text-anchor="middle">база</text>')],
        beats=[["Раз.", "Два."]])
    tl = timeline_for(script)
    b0, b1 = tl.scenes[0].beats
    with FrameRenderer(script, tl) as r:
        op = "() => document.querySelector('#c').parentNode.getAttribute('opacity')"
        r.page.evaluate("t => window.seek(t)", b0.start + 0.3)
        assert float(r.page.evaluate(op)) == 0, "до своей реплики элемент скрыт"
        r.page.evaluate("t => window.seek(t)", b1.start + 1.0)
        assert float(r.page.evaluate(op)) == 1


def test_draw_animation_progresses_stroke():
    script = make_script([svg_with(
        '<path id="p" d="M100 500 L900 500" stroke="#fff" stroke-width="8" fill="none" data-beat="0" data-anim="draw"/>'
        '<text x="540" y="900" font-size="60" text-anchor="middle">t</text>')])
    tl = timeline_for(script)
    start = tl.scenes[0].beats[0].start
    with FrameRenderer(script, tl) as r:
        off = "() => parseFloat(document.querySelector('#p').style.strokeDashoffset || '0')"
        r.page.evaluate("t => window.seek(t)", start + 0.3)
        mid = r.page.evaluate(off)
        r.page.evaluate("t => window.seek(t)", start + 2.0)
        end = r.page.evaluate(off)
    assert mid > 0 and end == 0


def test_lint_is_clean_for_a_good_scene():
    assert lint('<text x="540" y="600" font-size="80" text-anchor="middle" data-beat="0">Привет</text>') == {}


def test_lint_flags_out_of_bounds_overlap_and_tiny_text():
    out = lint('<text x="1000" y="600" font-size="80" data-beat="0">Слишком длинная подпись</text>')
    assert any("выходит" in p for p in out[0])

    out = lint('<text x="540" y="600" font-size="80" text-anchor="middle">Наложение</text>'
               '<text x="560" y="610" font-size="80" text-anchor="middle">Другое</text>')
    assert any("перекрываются" in p for p in out[0])

    out = lint('<text x="540" y="600" font-size="20" text-anchor="middle">мелко</text>')
    assert any("мелкий" in p for p in out[0])


def test_sample_script_has_no_layout_problems():
    script = Script.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    with FrameRenderer(script, timeline_for(script)) as r:
        assert r.lint() == {}


def test_preview_command_writes_pngs(tmp_path):
    assert main(["preview", str(SAMPLE), "-o", str(tmp_path)]) == 0
    pngs = sorted((tmp_path / "preview").glob("scene_*.png"))
    assert len(pngs) == 5
    assert png_size(pngs[0].read_bytes()) == (1080, 1920)


def test_invalid_script_stops_render_with_exit_code_2(tmp_path, capsys):
    bad = make_script([GOOD_SVG.replace("0 0 1080 1150", "0 0 1 1")])
    p = tmp_path / "s.json"
    p.write_text(bad.model_dump_json(), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main(["render", str(p), "--no-voice", "-o", str(tmp_path / "o")])
    assert e.value.code == 2
    assert "viewBox" in capsys.readouterr().err


@needs_ffmpeg
def test_full_render_with_voice_track_produces_vertical_video_with_audio(tmp_path, monkeypatch):
    async def fake(text, voice, rate, mp3, meta):
        make_tone(mp3, 0.8)
        meta.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(tts, "_synth_one", fake)
    script = make_script([GOOD_SVG, GOOD_SVG], beats=[["Раз два.", "Три."], ["Четыре."]])
    p = tmp_path / "s.json"
    p.write_text(script.model_dump_json(), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["render", str(p), "-o", str(out), "--fps", "10"]) == 0

    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out / "video.mp4")],
        capture_output=True, text=True, check=True).stdout)
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (1080, 1920)
    assert kinds["video"]["codec_name"] == "h264" and "audio" in kinds
    tl = build_timeline(tts.synthesize(script, out / "audio"))
    assert float(info["format"]["duration"]) == pytest.approx(tl.total, abs=0.3)
