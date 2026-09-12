from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from nonebot.adapters import Event
from nonebot.consts import ENDSWITH_KEY, STARTSWITH_KEY

from ironsbot.core.affix_commands import AffixArgument, AffixCommand
from ironsbot.integrations.onebot.rules import BOT_COMMAND_ARG_KEY, affix_command
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot


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
@pytest.mark.asyncio
async def test_pure_parser_and_onebot_argument_state_agree(
    text: str, expected: AffixArgument | None
) -> None:
    parser = AffixCommand(("技能",), ("技能",))
    assert parser(text) == expected
    state = {}
    matched = await affix_command(parser)(
        cast("Bot", None), private_message_event(text), state
    )
    assert matched is (expected is not None)
    if expected is None:
        assert state == {}
    else:
        assert state == {
            STARTSWITH_KEY: expected.prefix,
            ENDSWITH_KEY: expected.suffix,
            BOT_COMMAND_ARG_KEY: expected.argument,
        }


def test_affixes_are_literal_ordered_and_case_configurable() -> None:
    parser = AffixCommand(("Ab", "Abc", "[+"), ("?]",))
    assert parser("aBc Value") == AffixArgument("aB", "", "c Value")
    assert parser("[+Value?]") == AffixArgument("[+", "?]", "Value")
    assert AffixCommand(("Ab",), (), ignorecase=False)("abValue") is None
    assert AffixCommand((), ("End",))("vEnD") == AffixArgument("", "EnD", "v")
    assert AffixCommand(("ab",), ("bc",))("abc") == AffixArgument("ab", "bc", "c")
    assert AffixCommand((), ())("anything") is None


@pytest.mark.asyncio
async def test_rule_without_plaintext_does_not_mutate_state() -> None:
    event = Mock(spec=Event)
    event.get_plaintext.side_effect = ValueError("no plaintext")
    state = {"other": "kept"}
    assert not await affix_command(AffixCommand(("query",), ()))(
        cast("Bot", None), event, state
    )
    assert state == {"other": "kept"}
