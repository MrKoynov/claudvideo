"""Формат сценария. Его пишет Claude, его же можно править руками перед рендером."""

from __future__ import annotations

from pydantic import BaseModel


class Scene(BaseModel):
    # Реплики диктора. Каждая реплика озвучивается отдельно: с неё начинается
    # показ элементов SVG с data-beat="<номер реплики>".
    beats: list[str]
    # Один <svg viewBox="0 0 1080 1150"> со схемой.
    svg: str


class Script(BaseModel):
    title: str  # короткая плашка вверху кадра
    youtube_title: str
    description: str
    hashtags: list[str]
    scenes: list[Scene]
    # Утверждения, которые стоит проверить по источникам до публикации.
    fact_check: list[str]
