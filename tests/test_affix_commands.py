from __future__ import annotations

import pytest

from ironsbot.core.affix_commands import AffixArgument, AffixCommand


@pytest.mark.parametrize(
    "text,expected",
    [
        ("技能盖亚", AffixArgument("技能", "", "盖亚")),
        ("盖亚技能", AffixArgument("", "技能", "盖亚")),
        ("技能盖亚技能", AffixArgument("技能", "技能", "盖亚")),
        ("技能", AffixArgument("技能", "技能", "")),
        ("技能 盖 亚 ", AffixArgument("技能", "", " 盖 亚 ")),
        ("看看技能盖亚吧", None),
        ("/技能盖亚", None),
        ("", None),
    ],
)
def test_affix_parser_preserves_argument_boundaries(
    text: str, expected: AffixArgument | None
) -> None:
    parser = AffixCommand(("技能",), ("技能",))
    assert parser(text) == expected


def test_affixes_are_literal_ordered_and_case_configurable() -> None:
    parser = AffixCommand(("Ab", "Abc", "[+"), ("?]",))
    assert parser("aBc Value") == AffixArgument("aB", "", "c Value")
    assert parser("[+Value?]") == AffixArgument("[+", "?]", "Value")
    assert AffixCommand(("Ab",), (), ignorecase=False)("abValue") is None
    assert AffixCommand((), ("End",))("vEnD") == AffixArgument("", "EnD", "v")
    assert AffixCommand(("ab",), ("bc",))("abc") == AffixArgument("ab", "bc", "c")
    assert AffixCommand((), ())("anything") is None


def test_affix_command_exposes_plain_argument_parser() -> None:
    parser = AffixCommand(("属性",), ("属性",))

    assert parser.parse_argument("属性圣灵") == "圣灵"
    assert parser.parse_argument("圣灵属性") == "圣灵"
    assert parser.parse_argument("普通消息") is None
