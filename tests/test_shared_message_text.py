from ironsbot.shared.messages.text import (
    command_text_matches,
    normalize_command_text,
    render_text,
    strip_command_prefix,
)


def test_normalize_command_text_removes_whitespace_and_lowercases() -> None:
    assert normalize_command_text(" X R Y M ") == "xrym"


def test_strip_command_prefix_uses_slash_by_default() -> None:
    assert strip_command_prefix("/回复行数 20") == "回复行数 20"
    assert strip_command_prefix("回复行数 20") is None


def test_command_text_matches_normalized_commands() -> None:
    assert command_text_matches(" X R Y M ", ["xrym"])
    assert not command_text_matches("xrym2", ["xrym"])


def test_render_text_expands_escaped_newlines() -> None:
    assert render_text("a\\nb") == "a\nb"
