# SPDX-License-Identifier: MIT
# ruff: noqa: FBT001, FBT002
import re
from typing import Literal

from nonebot.adapters import Event
from nonebot.consts import ENDSWITH_KEY, STARTSWITH_KEY
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.runtime.message_input import (
    MessageInputKind,
    is_self_command,
    message_input_context,
)

BOT_COMMAND_ARG_KEY: Literal["_irons_bot_command_arg"] = "_irons_bot_command_arg"


class StartswithOrEndswithRule:
    """检查消息纯文本是否以指定字符串开头或结尾（OR 语义）。

    匹配成功后始终设置 STARTSWITH_KEY 和 ENDSWITH_KEY（未命中侧为空字符串），
    并设置 BOT_COMMAND_ARG_KEY 为去除前缀/后缀后的文本。
    """

    __slots__ = ("ignorecase", "prefixes", "suffixes")

    def __init__(
        self,
        prefixes: tuple[str, ...],
        suffixes: tuple[str, ...],
        ignorecase: bool = False,
    ) -> None:
        self.prefixes = prefixes
        self.suffixes = suffixes
        self.ignorecase = ignorecase

    def __repr__(self) -> str:
        return (
            f"StartswithOrEndswith("
            f"prefixes={self.prefixes}, suffixes={self.suffixes}, "
            f"ignorecase={self.ignorecase})"
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, StartswithOrEndswithRule)
            and frozenset(self.prefixes) == frozenset(other.prefixes)
            and frozenset(self.suffixes) == frozenset(other.suffixes)
            and self.ignorecase == other.ignorecase
        )

    def __hash__(self) -> int:
        return hash(
            (frozenset(self.prefixes), frozenset(self.suffixes), self.ignorecase)
        )

    async def __call__(self, event: Event, state: T_State) -> bool:
        try:
            text = event.get_plaintext()
        except Exception:  # noqa: BLE001
            return False

        flags = re.IGNORECASE if self.ignorecase else 0

        sw = (
            re.match(
                f"^(?:{'|'.join(re.escape(p) for p in self.prefixes)})",
                text,
                flags,
            )
            if self.prefixes
            else None
        )
        ew = (
            re.search(
                f"(?:{'|'.join(re.escape(s) for s in self.suffixes)})$",
                text,
                flags,
            )
            if self.suffixes
            else None
        )

        if not sw and not ew:
            return False

        state[STARTSWITH_KEY] = sw.group() if sw else ""
        state[ENDSWITH_KEY] = ew.group() if ew else ""
        arg_start = sw.end() if sw else 0
        arg_end = len(text)
        if ew and ew.start() >= arg_start:
            arg_end = ew.start()
        state[BOT_COMMAND_ARG_KEY] = text[arg_start:arg_end]
        return True


def startswith_or_endswith(
    prefixes: str | tuple[str, ...],
    suffixes: str | tuple[str, ...] | None = None,
    ignorecase: bool = True,
) -> Rule:
    """匹配消息开头或结尾为指定字符串的规则。

    Args:
        prefixes: 前缀或前缀元组
        suffixes: 后缀或后缀元组，为 None 时复用 prefixes
        ignorecase: 是否忽略大小写
    """
    if suffixes is None:
        suffixes = prefixes
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    if isinstance(suffixes, str):
        suffixes = (suffixes,)
    return Rule(StartswithOrEndswithRule(prefixes, suffixes, ignorecase))


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
            return (
                not is_self_command(event) and context.kind is MessageInputKind.DIRECT
            )
        if context.kind is MessageInputKind.BOT_MENTION:
            return False
        if context.kind is MessageInputKind.MEMBER_MENTION:
            return self.allow_member_mentions
        if context.kind is MessageInputKind.REPLY:
            return self.allow_member_mentions or not context.has_member_mentions
        return True


def explicit_command() -> Rule:
    """Accept explicit commands, never direct or quoted ordinary-member @."""

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
        return (
            not is_self_command(event) and context.kind is MessageInputKind.BOT_MENTION
        )

    return Rule(_matches)


def bot_mention_including_reply() -> Rule:
    """Accept a current-message bot @, including when it accompanies a reply."""

    async def _matches(event: Event, _: T_State) -> bool:
        return not is_self_command(event) and message_input_context(event).mentions_bot

    return Rule(_matches)


def natural_language() -> Rule:
    """Allow natural language only when it is direct and has no @ segments."""

    return Rule(_InputStrategy("natural_language"))
