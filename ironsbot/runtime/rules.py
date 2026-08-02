# SPDX-License-Identifier: MIT
# ruff: noqa: FBT001, FBT002
import re
from typing import Literal

from nonebot.adapters import Event
from nonebot.consts import ENDSWITH_KEY, STARTSWITH_KEY
from nonebot.rule import Rule
from nonebot.typing import T_State

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


class DirectMessageOnly:
    """Match direct messages without reply or ``@`` segments."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "DirectMessageOnly()"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, DirectMessageOnly)

    def __hash__(self) -> int:
        return hash(())

    async def __call__(self, event: Event, _: T_State) -> bool:
        reply = getattr(event, "reply", None)
        return reply is None


def direct_message_only() -> Rule:
    """Restrict natural-language handling to non-reply, non-mention input."""

    return Rule(DirectMessageOnly()) & Rule(NoAt())


class CommandInput:
    """Accept command input after replies while keeping direct mentions isolated."""

    __slots__ = ("allow_direct_mentions",)

    def __init__(self, *, allow_direct_mentions: bool = False) -> None:
        self.allow_direct_mentions = allow_direct_mentions

    def __repr__(self) -> str:
        return f"CommandInput(allow_direct_mentions={self.allow_direct_mentions})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CommandInput)
            and self.allow_direct_mentions == other.allow_direct_mentions
        )

    def __hash__(self) -> int:
        return hash(self.allow_direct_mentions)

    async def __call__(self, event: Event, state: T_State) -> bool:
        if getattr(event, "reply", None) is not None:
            return True
        return self.allow_direct_mentions or await NoAt()(event, state)


def command_input(*, allow_direct_mentions: bool = False) -> Rule:
    """Accept explicit commands, including commands sent after a reply.

    A direct message containing ``@`` remains reserved for mention handling,
    unless the command explicitly parses a manual ``@`` target itself.
    When the message replies to another message, only the new message content
    is parsed by matchers and its mention segments are intentionally ignored.
    """

    return Rule(CommandInput(allow_direct_mentions=allow_direct_mentions))


class NoAt:
    """仅匹配没有 @ 段的消息，避免 @机器人/他人 后面的文本误触发命令。"""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NoAt()"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NoAt)

    def __hash__(self) -> int:
        return hash(())

    async def __call__(self, event: Event, _: T_State) -> bool:
        message = getattr(event, "message", None)
        if message is None:
            return True

        for segment in message:
            if getattr(segment, "type", None) != "at":
                continue
            return False

        return True
