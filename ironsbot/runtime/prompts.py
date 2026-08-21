# SPDX-License-Identifier: MIT
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable, signature
from typing import Any, Generic, TypeAlias, TypeVar, cast, overload

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
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
    EXPLICIT_COMMAND_STATE_KEY,
    begin_queued_conversation,
    get_prompt_session_manager,
    reject_with_rule,
)
from ironsbot.runtime.matchers import (
    enter_prompt_loop as _enter_prompt_loop,
)
from ironsbot.runtime.prompt_errors import PromptSessionManagerMissingError
from ironsbot.runtime.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)

T = TypeVar("T")


class PromptItem(NamedTuple, Generic[T]):
    name: str
    desc: str
    value: T
    is_sub_prompt: bool = False
    semantic_target: SemanticTarget | None = None
    key: str | None = None
    is_visible: bool = True


@dataclass
class Prompt(Generic[T]):
    title: str
    items: list[PromptItem[T]]
    at_user_id: int | None = None
    action: ActionDefinition | None = None
    page_id: str = "root"

    def __post_init__(self) -> None:
        if not self.title.endswith("\n"):
            self.title = self.title + "\n"
        if any(not item.is_visible for item in self.items):
            keys = [item.key for item in self.items]
            if any(not key for key in keys):
                msg = "hidden prompt items require explicit keys for every item"
                raise ValueError(msg)
            if len(keys) != len(set(keys)):
                msg = "hidden prompt item keys must be unique"
                raise ValueError(msg)

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

    def get_item_by_input(self, value: str) -> PromptItem[T] | None:
        """Resolve either a normal numeric choice or an explicitly keyed choice."""
        if any(item.key is not None for item in self.items):
            return next((item for item in self.items if item.key == value), None)
        return self.get_item(int(value)) if value.isdigit() else None

    def build_message(self) -> str:
        if any(item.key is not None for item in self.items):
            lines = [self.title.rstrip()]
            for item in self.items:
                if not item.is_visible:
                    continue
                key = item.key or "?"
                indent = "   " if item.is_sub_prompt else ""
                text = f"{indent}{key}. {item.name}"
                if item.desc:
                    text += f"（{item.desc}）"
                lines.append(text)
            lines.append("\n输入编号查看详情 · 输入 0 退出")
            return "\n".join(lines)
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
PromptResolverWithoutEvent: TypeAlias = Callable[[Any, Matcher], Awaitable[None]]
PromptResolverWithEvent: TypeAlias = Callable[
    [Any, Matcher, Event],
    Awaitable[None],
]
PromptResolver: TypeAlias = (
    PromptResolverWithoutEvent | PromptResolverWithEvent
)


def _is_digit_input(event: Event) -> bool:
    """只匹配纯数字消息（含 ``"0"``），用于限制临时 Matcher 的触发范围。"""
    return event.get_plaintext().strip().isdigit()


@run_preprocessor
async def _invalidate_prompt_on_command(matcher: Matcher, event: Event) -> None:
    if not matcher.state.get(EXPLICIT_COMMAND_STATE_KEY, False):
        return
    try:
        prompt_sessions = get_prompt_session_manager(matcher)
    except PromptSessionManagerMissingError:
        return
    # A new explicit command takes ownership of this conversation.  Menu routers
    # and natural-language handlers are intentionally not marked this way.
    prompt_sessions.invalidate(event.get_session_id())
    prompt_sessions.invalidate_event_conversations(event)


async def enter_prompt(  # noqa: PLR0913
    matcher: Matcher,
    event: Event,
    state: T_State,
    prompt: Prompt[Any],
    resolver: PromptResolver,
    input_check: Callable[[Event], bool] | None = None,
    prompt_message: str | Message | Awaitable[str | Message] | None = None,
) -> None:
    """发送 Prompt 并进入选择循环（替代 ``matcher.got``）。"""
    state[PROMPT_STATE_KEY] = prompt
    session_id = event.get_session_id()
    prompt_sessions = get_prompt_session_manager(matcher)
    version = prompt_sessions.acquire(session_id)
    input_check = input_check or _is_digit_input
    rule = prompt_sessions.make_rule(session_id, version, input_check)

    handler = _create_selection_handler(
        resolver,
        session_id,
        version,
        input_check,
    )

    def queue_reply_check(next_event: Event) -> bool:
        return next_event.get_session_id() == session_id and input_check(next_event)

    # Image-backed menus can take noticeable time to render.  Reserve the
    # selection shape before awaiting that work so a quick ``a1`` or ``1`` is
    # not routed to an unrelated matcher such as AI chat.
    rendered_prompt = prompt_message
    if isawaitable(rendered_prompt):
        await begin_queued_conversation(
            matcher,
            [handler],
            namespace="selection_prompt",
            pending_reply_check=queue_reply_check,
            queue_reply_check=queue_reply_check,
            queue_group_reply_check=input_check,
            queue_page_id=prompt.page_id,
            queue_semantic_request_resolver=_prompt_semantic_request,
        )
        try:
            rendered_prompt = await rendered_prompt
        except BaseException:
            prompt_sessions.cancel_queued_conversation(matcher.state)
            raise

    await _enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=(
            prompt.build_event_message(event)
            if rendered_prompt is None
            else rendered_prompt
        ),
        queue_namespace="selection_prompt",
        queue_reply_check=queue_reply_check,
        queue_group_reply_check=input_check,
        queue_page_id=prompt.page_id,
        queue_semantic_request_resolver=_prompt_semantic_request,
    )


def _prompt_semantic_request(
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    prompt = state.get(PROMPT_STATE_KEY)
    if not isinstance(prompt, Prompt):
        return None
    text = event.get_plaintext().strip()
    item = prompt.get_item_by_input(text)
    if item is None:
        return None
    target = item.semantic_target or SemanticTarget(
        key=f"{item.name}\x1f{item.desc}",
        display=item.name,
    )
    action = prompt.action or ActionDefinition(
        id="selection_prompt",
        label="选择菜单",
    )
    return SemanticRequest(
        action=action,
        target=target,
        source=SemanticRequestSource.MENU,
    )


def _create_selection_handler(
    resolver: PromptResolver,
    session_id: str,
    version: int,
    input_check: Callable[[Event], bool],
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

        prompt = cast("Prompt[Any]", state[PROMPT_STATE_KEY])
        if (item := prompt.get_item_by_input(key_text)) is None:
            await matcher.finish("⚠️序号超出范围，已退出选择")

        if len(signature(resolver).parameters) >= RESOLVER_WITH_EVENT_PARAM_COUNT:
            event_resolver = cast("PromptResolverWithEvent", resolver)
            await event_resolver(item, matcher, event)
        else:
            plain_resolver = cast("PromptResolverWithoutEvent", resolver)
            await plain_resolver(item, matcher)

        rule = get_prompt_session_manager(matcher).make_rule(
            session_id,
            version,
            input_check,
        )
        await reject_with_rule(matcher, rule)

    return _handler
