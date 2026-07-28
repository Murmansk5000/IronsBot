# SPDX-License-Identifier: MIT
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import signature
from typing import Any, Generic, TypeAlias, TypeVar, cast, overload

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.message import run_preprocessor
from nonebot.typing import T_State
from typing_extensions import NamedTuple

from ironsbot.core.selection import (
    SelectionMenuItem,
    format_selection_menu,
)
from ironsbot.runtime.matchers import (
    PromptSessionManagerMissingError,
    get_prompt_session_manager,
    reject_with_rule,
)
from ironsbot.runtime.matchers import (
    enter_prompt_loop as _enter_prompt_loop,
)

T = TypeVar("T")


class PromptItem(NamedTuple, Generic[T]):
    name: str
    desc: str
    value: T
    is_sub_prompt: bool = False


@dataclass
class Prompt(Generic[T]):
    title: str
    items: list[PromptItem[T]]
    at_user_id: int | None = None

    def __post_init__(self) -> None:
        if not self.title.endswith("\n"):
            self.title = self.title + "\n"

    @overload
    def get(self, index: int) -> T | None: ...
    @overload
    def get(self, index: int, default: T) -> T: ...
    def get(self, index: int, default: T | None = None) -> T | None:
        try:
            return self.items[index - 1].value
        except IndexError:
            return default

    def get_item(self, index: int) -> PromptItem[T] | None:
        try:
            return self.items[index - 1]
        except IndexError:
            return None

    def build_message(self) -> str:
        return format_selection_menu(
            title=self.title.rstrip(),
            items=tuple(
                SelectionMenuItem(
                    label=f"{item.name}（{item.desc}）",
                    is_sub_item=item.is_sub_prompt,
                )
                for item in self.items
            ),
        )

    def build_event_message(self, event: Event) -> str | Message:
        text = self.build_message()
        if not isinstance(event, GroupMessageEvent):
            return text
        if self.at_user_id is None:
            self.at_user_id = event.user_id

        message = Message()
        message += MessageSegment.at(self.at_user_id)
        message += MessageSegment.text(" ")
        message += MessageSegment.text(text)
        return message


PROMPT_STATE_KEY = "prompt"
RESOLVER_WITH_EVENT_PARAM_COUNT = 3
PromptResolver: TypeAlias = Callable[[Any, Matcher], Awaitable[None]]
PromptResolverWithEvent: TypeAlias = Callable[
    [Any, Matcher, Event],
    Awaitable[None],
]


def _is_digit_input(event: Event) -> bool:
    """只匹配纯数字消息（含 ``"0"``），用于限制临时 Matcher 的触发范围。"""
    return event.get_plaintext().strip().isdigit()


@run_preprocessor
async def _invalidate_prompt_on_command(matcher: Matcher, event: Event) -> None:
    if matcher.priority > 0:
        try:
            prompt_sessions = get_prompt_session_manager(matcher)
        except PromptSessionManagerMissingError:
            return
        prompt_sessions.invalidate_event_conversations(event)
        prompt_sessions.invalidate(event.get_session_id())


async def enter_prompt(
    matcher: Matcher,
    event: Event,
    state: T_State,
    prompt: Prompt[Any],
    resolver: PromptResolver,
) -> None:
    """发送 Prompt 并进入选择循环（替代 ``matcher.got``）。"""
    state[PROMPT_STATE_KEY] = prompt
    session_id = event.get_session_id()
    prompt_sessions = get_prompt_session_manager(matcher)
    version = prompt_sessions.acquire(session_id)
    rule = prompt_sessions.make_rule(session_id, version, _is_digit_input)

    handler = _create_selection_handler(
        resolver,
        session_id,
        version,
    )

    await _enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=prompt.build_event_message(event),
        queue_namespace="selection_prompt",
        queue_reply_check=lambda next_event: (
            next_event.get_session_id() == session_id
            and _is_digit_input(next_event)
        ),
    )


def _create_selection_handler(
    resolver: PromptResolver,
    session_id: str,
    version: int,
) -> Callable[..., Awaitable[None]]:
    """创建选择循环 handler（从 event 读取输入，不依赖 got）。"""

    async def _handler(
        matcher: Matcher,
        event: Event,
        state: T_State,
    ) -> None:
        if PROMPT_STATE_KEY not in state:
            raise FinishedException

        key_text = event.get_plaintext().strip()

        if key_text == "0":
            await matcher.finish("❌已退出查询")

        if not key_text.isdigit():
            raise FinishedException

        prompt = cast("Prompt[Any]", state[PROMPT_STATE_KEY])
        if (item := prompt.get_item(int(key_text))) is None:
            await matcher.finish("⚠️序号超出范围，已退出选择")

        if len(signature(resolver).parameters) >= RESOLVER_WITH_EVENT_PARAM_COUNT:
            event_resolver = cast("PromptResolverWithEvent", resolver)
            await event_resolver(item, matcher, event)
        else:
            await resolver(item, matcher)

        rule = get_prompt_session_manager(matcher).make_rule(
            session_id,
            version,
            _is_digit_input,
        )
        await reject_with_rule(matcher, rule)

    return _handler
