from types import SimpleNamespace

import pytest

from claudvideo import scriptgen
from claudvideo.scriptgen import Repair, SceneFix, generate_script
from claudvideo.prompts import repair_prompt, system_prompt
from tests.conftest import GOOD_SVG, make_script

BAD_SVG = GOOD_SVG.replace("0 0 1080 1150", "0 0 500 500")


class FakeClient:
    """Подмена anthropic.Anthropic: отдаёт заготовленные ответы и запоминает вызовы."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, SimpleNamespace):
            return r
        return SimpleNamespace(stop_reason="end_turn", parsed_output=r)


def test_clean_script_needs_one_call():
    c = FakeClient(make_script())
    s = generate_script("тема", client=c, lint=False)
    assert len(c.calls) == 1 and s.title == "Тест"


def test_call_uses_default_model_effort_schema_and_fallbacks():
    c = FakeClient(make_script())
    generate_script("тема", duration=30, client=c, lint=False)
    kw = c.calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["output_format"].__name__ == "Script"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert "Тема: тема" in kw["messages"][0]["content"] and "30" in kw["messages"][0]["content"]


def test_no_fallbacks_for_models_that_do_not_support_them():
    c = FakeClient(make_script())
    generate_script("тема", model="claude-haiku-5-5", client=c, lint=False)
    assert "fallbacks" not in c.calls[0] and "betas" not in c.calls[0]


def test_broken_scene_is_repaired_and_other_scenes_untouched():
    script = make_script([BAD_SVG, GOOD_SVG])
    other = script.scenes[1].svg
    repair = Repair(fixes=[SceneFix(scene_number=1, svg=GOOD_SVG),
                           SceneFix(scene_number=2, svg="<svg>чужая сцена</svg>")])
    c = FakeClient(script, repair)
    out = generate_script("тема", client=c, lint=False)
    assert len(c.calls) == 2
    assert out.scenes[0].svg == GOOD_SVG
    assert out.scenes[1].svg == other, "сцену без проблем править нельзя"
    prompt = c.calls[1]["messages"][0]["content"]
    assert "Сцена 1" in prompt and "viewBox" in prompt and "Сцена 2" not in prompt
    assert c.calls[1]["output_format"].__name__ == "Repair"


def test_repair_gives_up_after_max_rounds_and_returns_script(capsys):
    script = make_script([BAD_SVG])
    still_bad = Repair(fixes=[SceneFix(scene_number=1, svg=BAD_SVG)])
    c = FakeClient(script, still_bad, still_bad)
    out = generate_script("тема", client=c, lint=False)
    assert len(c.calls) == 1 + scriptgen.MAX_REPAIR_ROUNDS
    assert out.scenes[0].svg == BAD_SVG
    assert "Остались замечания" in capsys.readouterr().err


def test_layout_lint_problems_are_sent_for_repair(monkeypatch):
    script = make_script([GOOD_SVG])
    calls = {"n": 0}

    def fake_lint(s):
        calls["n"] += 1
        return {0: ["текст «Привет» выходит за безопасную зону"]} if calls["n"] == 1 else {}

    monkeypatch.setattr(scriptgen, "lint_layout", fake_lint)
    c = FakeClient(script, Repair(fixes=[SceneFix(scene_number=1, svg=GOOD_SVG)]))
    generate_script("тема", client=c, lint=True)
    assert "выходит за безопасную зону" in c.calls[1]["messages"][0]["content"]


@pytest.mark.parametrize("stop, fragment", [("refusal", "отказалась"), ("max_tokens", "лимит")])
def test_refusal_and_truncation_raise_clear_errors(stop, fragment):
    c = FakeClient(SimpleNamespace(stop_reason=stop, parsed_output=None))
    with pytest.raises(RuntimeError, match=fragment):
        generate_script("тема", client=c, lint=False)


def test_unparsed_output_raises():
    c = FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=None))
    with pytest.raises(RuntimeError, match="не по схеме"):
        generate_script("тема", client=c, lint=False)


def test_system_prompt_is_filled_in():
    p = system_prompt(40)
    assert "520" in p  # 40 с * 13 символов
    assert "__EXAMPLE" not in p and "{chars}" not in p
    assert 'viewBox="0 0 1080 1150"' in p and "markerUnits" in p


def test_repair_prompt_numbers_scenes_from_one():
    s = make_script([GOOD_SVG, GOOD_SVG])
    p = repair_prompt(s.scenes, {1: ["проблема"]})
    assert "Сцена 2" in p and "проблема" in p and "Сцена 1" not in p


@pytest.mark.parametrize("model", [scriptgen.Script, Repair])
def test_schemas_are_accepted_by_sdk_structured_output_transform(model):
    """Ту же трансформацию SDK делает внутри messages.parse; без сети проверяем, что схема проходит."""
    from anthropic import transform_schema
    from pydantic import TypeAdapter

    schema = transform_schema(TypeAdapter(model).json_schema())
    assert schema["type"] == "object" and schema.get("additionalProperties") is False
