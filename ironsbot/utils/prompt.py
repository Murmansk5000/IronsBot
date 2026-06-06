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
from sqlmodel import Session
from typing_extensions import NamedTuple

from ironsbot.utils import build_sub_line
from ironsbot.utils.matcher import (
    enter_prompt_loop as _enter_prompt_loop,
)
from ironsbot.utils.matcher import (
    prompt_session_manager,
    reject_with_rule,
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
        msg = self.title
        for index, item in enumerate(self.items, start=1):
            text = f"{index}. {item.name}（{item.desc}）"
            if item.is_sub_prompt:
                msg += build_sub_line(texts=[text])
            else:
                msg += f"{text}\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        return msg

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
RESOLVER_WITH_EVENT_PARAM_COUNT = 4
PromptResolver: TypeAlias = Callable[[Any, Matcher, Any], Awaitable[None]]


def _is_digit_input(event: Event) -> bool:
    """只匹配纯数字消息（含 ``"0"``），用于限制临时 Matcher 的触发范围。"""
    return event.get_plaintext().strip().isdigit()


@run_preprocessor
async def _invalidate_prompt_on_command(matcher: Matcher, event: Event) -> None:
    if matcher.priority > 0:
        prompt_session_manager.invalidate(event.get_session_id())


async def enter_prompt(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    prompt: Prompt[Any],
    resolver: PromptResolver,
    *,
    session_dependency: Any | None = None,
) -> None:
    """发送 Prompt 并进入选择循环（替代 ``matcher.got``）。

    ``session_dependency`` 可传入 ``Depends(...)``，
    用于让调用方自行决定传入的数据库会话依赖。
    """
    state[PROMPT_STATE_KEY] = prompt
    session_id = event.get_session_id()
    version = prompt_session_manager.acquire(session_id)
    rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)

    handler = _create_selection_handler(
        resolver,
        session_id,
        version,
        session_dependency,
    )

    await _enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=prompt.build_event_message(event),
    )


def _create_selection_handler(
    resolver: PromptResolver,
    session_id: str,
    version: int,
    session_dependency: Any,
) -> Callable[..., Awaitable[None]]:
    """创建选择循环 handler（从 event 读取输入，不依赖 got）。"""

    async def _handler(
        matcher: Matcher,
        event: Event,
        state: T_State,
        session: Session,
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
            await resolver(item, matcher, session, event)
        else:
            await resolver(item, matcher, session)

        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        await reject_with_rule(matcher, rule)

    if session_dependency is not None:
        _handler.__annotations__["session"] = session_dependency

    return _handler
