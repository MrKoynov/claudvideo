"""Статическая проверка SVG-сцен, которые пишет LLM.

Мы не чиним SVG молча, а возвращаем список проблем: их можно показать
пользователю или отправить обратно Claude на исправление.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

SCENE_W = 1080
SCENE_H = 1150
VIEWBOX = f"0 0 {SCENE_W} {SCENE_H}"

FORBIDDEN_TAGS = {"script", "foreignobject", "image", "iframe", "style", "animate",
                  "animatetransform", "animatemotion", "set"}


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def check_svg(svg: str, n_beats: int) -> list[str]:
    """Вернуть список проблем; пустой список значит, что SVG годится."""
    problems: list[str] = []
    if re.search(r"<!(DOCTYPE|ENTITY)", svg, re.I):
        return ["DOCTYPE/ENTITY запрещены"]
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"SVG не парсится как XML: {e}"]

    if _local(root.tag) != "svg":
        return ["корневой элемент должен быть <svg>"]
    if " ".join(root.get("viewBox", "").replace(",", " ").split()) != VIEWBOX:
        problems.append(f'у корневого <svg> должен быть viewBox="{VIEWBOX}"')

    seen_text = False
    for el in root.iter():
        tag = _local(el.tag)
        if tag in FORBIDDEN_TAGS:
            problems.append(f"элемент <{tag}> запрещён (анимацию делает рендерер через data-атрибуты)")
        if tag == "text":
            seen_text = True
        for attr, val in el.attrib.items():
            a = _local(attr)
            if a.startswith("on"):
                problems.append(f"атрибут {a} запрещён")
            if a == "href" and not val.startswith("#"):
                problems.append("внешние ссылки href запрещены")
            if "http://" in val or "https://" in val:
                if a not in ("xmlns",) and not attr.startswith("{http://www.w3.org/2000/xmlns"):
                    problems.append(f"URL в атрибуте {a} запрещён")
            if a == "data-beat":
                if not val.isdigit() or int(val) >= n_beats:
                    problems.append(
                        f'data-beat="{val}" вне диапазона: в сцене {n_beats} реплик (индексы 0..{n_beats - 1})'
                    )
            if a == "data-anim" and val not in ANIMS:
                problems.append(f'неизвестный data-anim="{val}", допустимо: {", ".join(sorted(ANIMS))}')
            if a == "data-loop" and val not in LOOPS:
                problems.append(f'неизвестный data-loop="{val}", допустимо: {", ".join(sorted(LOOPS))}')

    if not seen_text:
        problems.append("в сцене нет ни одной подписи <text>: схема без подписей непонятна")
    # Дубликаты сообщений ни к чему.
    return list(dict.fromkeys(problems))


ANIMS = {"fade", "pop", "slide", "draw"}
LOOPS = {"pulse", "float", "spin", "wiggle", "flow"}


def check_script(script) -> dict[int, list[str]]:
    """Проблемы по сценам (индексы с нуля). Пустой словарь значит, что всё в порядке."""
    found: dict[int, list[str]] = {}
    for i, sc in enumerate(script.scenes):
        probs = check_svg(sc.svg, len(sc.beats))
        if not sc.beats or any(not b.strip() for b in sc.beats):
            probs.append("у сцены нет реплик или есть пустая реплика")
        if probs:
            found[i] = probs
    return found
