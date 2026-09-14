# SPDX-License-Identifier: MIT
from typing import Literal

from nonebot.adapters import Event
from nonebot.consts import ENDSWITH_KEY, STARTSWITH_KEY
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.core.affix_commands import AffixParser
from ironsbot.core.message_input import MessageInputKind
from ironsbot.integrations.onebot.message_input import message_input_context

BOT_COMMAND_ARG_KEY: Literal["_irons_bot_command_arg"] = "_irons_bot_command_arg"


def affix_command(parser: AffixParser) -> Rule:
    """Adapt a domain parser to NoneBot's existing query argument state."""

    async def matches(event: Event, state: T_State) -> bool:
        try:
            text = event.get_plaintext()
        except Exception:  # noqa: BLE001
            return False

        parsed = parser(text)
        if parsed is None:
            return False
        state[STARTSWITH_KEY] = parsed.prefix
        state[ENDSWITH_KEY] = parsed.suffix
        state[BOT_COMMAND_ARG_KEY] = parsed.argument
        return True

    return Rule(matches)


class _InputStrategy:
    """Declarative command admission with a narrow, explicit @ contract."""

    __slots__ = ("allow_member_mentions", "many_members", "name")

    def __init__(
        self,
        name: str,
        *,
        allow_member_mentions: bool = False,
        many_members: bool = False,
    ) -> None:
        self.name = name
        self.allow_member_mentions = allow_member_mentions
        self.many_members = many_members

    def __repr__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, _InputStrategy)
            and self.name == other.name
            and self.allow_member_mentions == other.allow_member_mentions
            and self.many_members == other.many_members
        )

    def __hash__(self) -> int:
        return hash((self.name, self.allow_member_mentions, self.many_members))

    async def __call__(self, event: Event, _: T_State) -> bool:
        context = message_input_context(event)
        if self.name == "natural_language":
            return context.kind is MessageInputKind.DIRECT
        if context.kind is MessageInputKind.BOT_MENTION:
            if context.has_member_mentions:
                return self.allow_member_mentions
            return self.name != "natural_language"
        if context.kind is MessageInputKind.MEMBER_MENTION:
            return self.allow_member_mentions
        if context.kind is MessageInputKind.REPLY:
            return self.allow_member_mentions or not context.has_member_mentions
        return True


def explicit_command() -> Rule:
    """Accept explicit commands, including commands addressed to the bot."""

    return Rule(_InputStrategy("explicit_command"))


def member_target_command() -> Rule:
    """Accept commands that explicitly allow one mentioned member target."""

    return Rule(
        _InputStrategy(
            "member_target_command",
            allow_member_mentions=True,
        )
    )


def member_targets_command() -> Rule:
    """Accept commands that intentionally manage mentioned member targets."""

    return Rule(
        _InputStrategy(
            "member_targets_command",
            allow_member_mentions=True,
            many_members=True,
        )
    )


def bot_mention() -> Rule:
    """Accept direct bot mentions only; quoted text remains explicit input."""

    async def _matches(event: Event, _: T_State) -> bool:
        context = message_input_context(event)
        return context.kind is MessageInputKind.BOT_MENTION

    return Rule(_matches)


def natural_language() -> Rule:
    """Allow natural language only when it is direct and has no @ segments."""

    return Rule(_InputStrategy("natural_language"))
