from ironsbot.shared.messaging.text import (
    build_message,
    command_text_matches,
    normalize_command_text,
    render_text,
    strip_command_prefix,
)


def test_normalize_command_text_removes_whitespace_and_lowercases() -> None:
    assert normalize_command_text(" X R Y M ") == "xrym"


def test_strip_command_prefix_uses_slash_by_default() -> None:
    assert strip_command_prefix("/更新数据") == "更新数据"
    assert strip_command_prefix("更新数据") is None


def test_command_text_matches_normalized_commands() -> None:
    assert command_text_matches(" X R Y M ", ["xrym"])
    assert not command_text_matches("xrym2", ["xrym"])


def test_render_text_expands_escaped_newlines() -> None:
    assert render_text("a\\nb") == "a\nb"


def test_build_message_renders_mentions_and_text() -> None:
    message = build_message("a\\nb", at_user_ids=[1, 1, 2])

    assert [segment.type for segment in message] == ["at", "text", "at", "text", "text"]
    assert message[0].data["qq"] == "1"
    assert message[2].data["qq"] == "2"
    assert message[-1].data["text"] == "a\nb"
