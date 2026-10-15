"""Командная строка: python -m claudvideo <make|script|render|preview> ..."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from .models import Script
from .svgcheck import check_script
from .timeline import build_timeline
from .tts import DEFAULT_VOICE


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE).strip("-")
    return (s[:limit].strip("-") or "video")


def load_script(path: Path) -> Script:
    return Script.model_validate_json(path.read_text(encoding="utf-8"))


def print_problems(found: dict[int, list[str]], header: str) -> None:
    print(header, file=sys.stderr)
    for i, probs in sorted(found.items()):
        for p in probs:
            print(f"  сцена {i + 1}: {p}", file=sys.stderr)


def print_meta(script: Script) -> None:
    print(f"\nНазвание: {script.youtube_title}")
    print(f"Описание: {script.description}")
    print("Теги: " + " ".join(script.hashtags))
    if script.fact_check:
        print("\nПроверьте факты перед публикацией:")
        for c in script.fact_check:
            print(f"  - {c}")


def cmd_script(args: argparse.Namespace) -> Script:
    from .scriptgen import generate_script

    script = generate_script(
        args.topic, duration=args.duration, model=args.model, effort=args.effort,
        lint=not args.no_lint,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    print(f"Сценарий: {out}")
    print_meta(script)
    return script


def render_pipeline(script: Script, out_dir: Path, args: argparse.Namespace) -> None:
    from .render import FrameRenderer, render_previews, render_video
    from .tts import synthesize

    found = check_script(script)
    if found:
        print_problems(found, "В сценарии есть ошибки, рендер остановлен:")
        raise SystemExit(2)

    silent = args.no_voice
    audio = synthesize(script, out_dir / "audio", voice=args.voice, rate=args.rate, silent=silent)
    tl = build_timeline(audio)
    print(f"Длительность ролика: {tl.total:.1f} с, сцен: {len(tl.scenes)}"
          + (" (без голоса, длительность оценена по тексту)" if silent else ""))

    if args.cmd == "preview":
        paths = render_previews(script, tl, out_dir / "preview")
        print("Превью сцен:\n  " + "\n  ".join(map(str, paths)))
        return

    from .audio import mix_track, write_wav

    if not args.no_lint:
        with FrameRenderer(script, tl) as r:
            issues = r.lint()
        if issues:
            print_problems(issues, "Предупреждения по вёрстке (проверьте превью):")

    pcm = mix_track(audio, tl, music=args.music, music_gain=args.music_gain)
    wav = out_dir / "audio" / "mix.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    write_wav(pcm, wav)

    video = Path(args.video) if getattr(args, "video", None) else out_dir / "video.mp4"
    render_video(script, tl, wav, video, fps=args.fps)
    print(f"Видео: {video}")
    if args.preview:
        paths = render_previews(script, tl, out_dir / "preview")
        print(f"Превью сцен: {paths[0].parent}")


def add_render_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--voice", default=DEFAULT_VOICE, help="голос edge-tts (по умолчанию %(default)s)")
    p.add_argument("--rate", default="+0%", help="скорость речи, например +10%% или -5%%")
    p.add_argument("--no-voice", action="store_true", help="без озвучки: тишина, длительность оценивается по тексту")
    p.add_argument("--music", help="файл фоновой музыки (mp3/wav), зацикливается")
    p.add_argument("--music-gain", type=float, default=0.12, help="громкость музыки, 0..1")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--no-lint", action="store_true", help="не проверять вёрстку")


def add_script_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--duration", type=int, default=40, help="целевая длительность, секунд")
    p.add_argument("--model", default=None, help="модель Claude (по умолчанию claude-opus-5-5)")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="claudvideo", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("make", help="тема -> готовое видео")
    p.add_argument("topic")
    p.add_argument("-o", "--output", help="папка результата (по умолчанию out/<тема>)")
    p.add_argument("--preview", action="store_true", help="сохранить стоп-кадры сцен")
    add_script_opts(p)
    add_render_opts(p)

    p = sub.add_parser("script", help="тема -> script.json (без озвучки и рендера)")
    p.add_argument("topic")
    p.add_argument("-o", "--output", default="script.json")
    p.add_argument("--no-lint", action="store_true", help="не проверять вёрстку в браузере")
    add_script_opts(p)

    p = sub.add_parser("render", help="script.json -> видео")
    p.add_argument("script")
    p.add_argument("-o", "--output", help="папка результата (по умолчанию рядом со сценарием)")
    p.add_argument("--video", help="путь к итоговому mp4")
    p.add_argument("--preview", action="store_true", help="сохранить стоп-кадры сцен")
    add_render_opts(p)

    p = sub.add_parser("preview", help="script.json -> стоп-кадры сцен (быстро, без озвучки и видео)")
    p.add_argument("script")
    p.add_argument("-o", "--output", help="папка результата (по умолчанию рядом со сценарием)")
    add_render_opts(p)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except TypeError as e:  # SDK бросает TypeError, когда не нашёл ключ
        if "authentication method" not in str(e):
            raise
        print("Не найден ключ Anthropic. Задайте переменную окружения ANTHROPIC_API_KEY "
              "(ключ создаётся в console.anthropic.com).", file=sys.stderr)
        return 1


def run(args: argparse.Namespace) -> int:
    if args.cmd == "script":
        cmd_script(args)
        return 0

    if args.cmd == "make":
        out_dir = Path(args.output or Path("out") / f"{datetime.now():%Y%m%d-%H%M}-{slugify(args.topic)}")
        args.output = str(out_dir / "script.json")
        args.no_lint = getattr(args, "no_lint", False)
        script = cmd_script(args)
        render_pipeline(script, out_dir, args)
        return 0

    path = Path(args.script)
    out_dir = Path(args.output) if args.output else path.parent / (path.stem + "_out")
    if args.cmd == "preview":
        args.no_voice = True  # превью не нуждается в озвучке
    render_pipeline(load_script(path), out_dir, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
