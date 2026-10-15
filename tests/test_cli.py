import pytest

from claudvideo.cli import build_parser, main, slugify


def test_slugify_keeps_cyrillic_and_trims():
    assert slugify("Почему у осьминога три сердца?!") == "почему-у-осьминога-три-сердца"
    assert slugify("???") == "video"
    assert len(slugify("а" * 100)) <= 40


@pytest.mark.parametrize("argv", [
    ["make", "тема"], ["script", "тема", "-o", "x.json"], ["render", "s.json"], ["preview", "s.json"],
    ["make", "тема", "--duration", "30", "--voice", "ru-RU-SvetlanaNeural", "--rate", "+10%",
     "--music", "m.mp3", "--no-voice", "--preview", "--effort", "high", "--model", "claude-sonnet-5-5"],
])
def test_parser_accepts_documented_commands(argv):
    build_parser().parse_args(argv)


def test_missing_api_key_gives_friendly_message(monkeypatch, capsys, tmp_path):
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # без профиля ant auth login
    assert main(["script", "тема", "-o", str(tmp_path / "s.json"), "--no-lint"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
