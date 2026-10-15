import json

import pytest

from claudvideo.models import Script
from claudvideo.svgcheck import check_script, check_svg
from tests.conftest import GOOD_SVG, ROOT, SAMPLE

VB = 'viewBox="0 0 1080 1150"'


def test_good_svg_passes():
    assert check_svg(GOOD_SVG, n_beats=1) == []


def test_sample_script_passes():
    script = Script.model_validate_json(SAMPLE.read_text(encoding="utf-8"))
    assert check_script(script) == {}


def test_example_scene_from_prompt_passes():
    ex = json.loads((ROOT / "claudvideo" / "example_scene.json").read_text(encoding="utf-8"))
    assert check_svg(ex["svg"], len(ex["beats"])) == []


def svg(body: str, head: str = VB) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" {head}>{body}<text>x</text></svg>'


@pytest.mark.parametrize("bad, fragment", [
    ('<svg viewBox="0 0 1080 1150"><text>x</text>', "XML"),
    ("<g/>", "корневой"),
    (svg("", head='viewBox="0 0 800 600"'), "viewBox"),
    (svg("<script>alert(1)</script>"), "script"),
    (svg('<rect width="1" height="1" onclick="x()"/>'), "onclick"),
    (svg('<image href="http://evil/x.png"/>'), "image"),
    (svg('<use href="https://evil/x.svg#a"/>'), "href"),
    (svg('<rect fill="url(https://evil/a)" width="1" height="1"/>'), "URL"),
    (svg("<style>text{fill:red}</style>"), "style"),
    (svg('<set attributeName="x" to="1"/>'), "set"),
    (svg('<rect data-beat="3" width="1" height="1"/>'), "data-beat"),
    (svg('<rect data-beat="x" width="1" height="1"/>'), "data-beat"),
    (svg('<rect data-anim="spiral" width="1" height="1"/>'), "data-anim"),
    (svg('<rect data-loop="bounce" width="1" height="1"/>'), "data-loop"),
    ('<!DOCTYPE svg [<!ENTITY a "b">]><svg viewBox="0 0 1080 1150"/>', "DOCTYPE"),
])
def test_bad_svg_is_reported(bad, fragment):
    problems = check_svg(bad, n_beats=2)
    assert problems, "ожидали проблемы"
    assert any(fragment in p for p in problems), problems


def test_svg_without_text_is_rejected():
    s = f'<svg xmlns="http://www.w3.org/2000/svg" {VB}><circle r="5"/></svg>'
    assert any("<text>" in p for p in check_svg(s, 1))


def test_internal_use_href_is_allowed():
    s = svg('<defs><path id="h" d="M0 0"/></defs><use href="#h"/>')
    assert check_svg(s, 1) == []


def test_empty_beats_reported():
    from tests.conftest import make_script

    sc = make_script(beats=[["  "]])
    assert 0 in check_script(sc)
