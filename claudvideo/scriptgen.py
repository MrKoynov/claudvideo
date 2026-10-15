"""Тема -> сценарий через Claude, с автоисправлением SVG по результатам проверок."""

from __future__ import annotations

import sys

import anthropic
from pydantic import BaseModel

from .models import Script
from .prompts import repair_prompt, system_prompt, user_prompt
from .svgcheck import check_script

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 20000  # потолок для запроса без стриминга
MAX_REPAIR_ROUNDS = 2
# Модели, которые принимают серверный fallback при отказе классификатора безопасности.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class SceneFix(BaseModel):
    scene_number: int  # с единицы, как в запросе
    svg: str


class Repair(BaseModel):
    fixes: list[SceneFix]


def _parse(client: anthropic.Anthropic, model: str, effort: str, system: str, user: str, fmt):
    """Один вызов с гарантированной JSON-схемой. Возвращает разобранный pydantic-объект."""
    kwargs = {}
    if model in FALLBACK_MODELS:
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    resp = client.beta.messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=fmt,
        output_config={"effort": effort},
        **kwargs,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(
            "Модель отказалась отвечать на эту тему (политика безопасности). Попробуйте другую формулировку."
        )
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(
            "Ответ не поместился в лимит токенов. Уменьшите --duration или снизьте --effort."
        )
    if resp.parsed_output is None:
        raise RuntimeError("Модель вернула ответ не по схеме. Повторите запуск.")
    return resp.parsed_output


def lint_layout(script: Script) -> dict[int, list[str]]:
    """Проверить вёрстку в настоящем браузере: текст в кадре, не перекрыт, не мелкий."""
    from .render import FrameRenderer
    from .timeline import build_timeline
    from .tts import synthesize

    tl = build_timeline(synthesize(script, workdir=None, silent=True))
    with FrameRenderer(script, tl) as r:
        return r.lint()


def _merge(a: dict[int, list[str]], b: dict[int, list[str]]) -> dict[int, list[str]]:
    out = {k: list(v) for k, v in a.items()}
    for k, v in b.items():
        out.setdefault(k, []).extend(v)
    return out


def find_problems(script: Script, lint: bool) -> dict[int, list[str]]:
    problems = check_script(script)
    if lint and not problems:  # на сломанном SVG верстку проверять бессмысленно
        problems = lint_layout(script)
    return problems


def generate_script(topic: str, duration: int = 40, model: str | None = None,
                    effort: str = "medium", lint: bool = True,
                    client: anthropic.Anthropic | None = None) -> Script:
    model = model or DEFAULT_MODEL
    client = client or anthropic.Anthropic()
    system = system_prompt(duration)

    print(f"Пишу сценарий ({model}) …", file=sys.stderr)
    script = _parse(client, model, effort, system, user_prompt(topic, duration), Script)

    for round_no in range(1, MAX_REPAIR_ROUNDS + 1):
        problems = find_problems(script, lint)
        if not problems:
            return script
        n = sum(len(v) for v in problems.values())
        print(f"Нашёл проблем: {n} в сценах {sorted(i + 1 for i in problems)}. "
              f"Исправляю (попытка {round_no}) …", file=sys.stderr)
        fixed = _parse(client, model, effort, system, repair_prompt(script.scenes, problems), Repair)
        for fx in fixed.fixes:
            i = fx.scene_number - 1
            if i in problems:  # чужие сцены не трогаем
                script.scenes[i].svg = fx.svg

    problems = find_problems(script, lint)
    if problems:
        print("Остались замечания (проверьте превью и поправьте script.json):", file=sys.stderr)
        for i, probs in sorted(problems.items()):
            for p in probs:
                print(f"  сцена {i + 1}: {p}", file=sys.stderr)
    return script
