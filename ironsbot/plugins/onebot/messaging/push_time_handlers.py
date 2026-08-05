from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.core.platform import ConversationRef
from ironsbot.runtime.matchers import enter_prompt_loop
from ironsbot.runtime.message_input import message_input_context
from ironsbot.services.messaging.push_time import (
    PushTimeOption,
    build_push_time_menu_prompt,
    normalize_push_time_input,
    push_time_value_prompt,
)

from .push_management_runtime import (
    PUSH_TIME_CONVERSATION_KEY,
    PUSH_TIME_FLOW,
    PUSH_TIME_OPTIONS_KEY,
    PUSH_TIME_SELECTED_KEY,
    OneBotConversationKind,
)

if TYPE_CHECKING:
    from ironsbot.services.messaging.service import MessagingService

RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


@dataclass(frozen=True)
class PushTimeValueContext:
    selected: int
    conversation: ConversationRef
    refresh_push_time_jobs: RefreshPushTimeJobs
    messaging: MessagingService


PushTimeHandler = Callable[[Matcher, MessageEvent, T_State], Awaitable[None]]


def build_push_time_menu_handler(
    refresh_push_time_jobs: RefreshPushTimeJobs,
    messaging: MessagingService,
) -> PushTimeHandler:
    def options_for(conversation: ConversationRef) -> list[PushTimeOption]:
        return messaging.push_time_options(conversation)

    async def handle_push_time_menu(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        conversation = message_input_context(event).message.conversation
        if conversation.kind not in {"private", "group"}:
            await matcher.finish()
        target_type = cast("OneBotConversationKind", conversation.kind)
        options = options_for(conversation)
        if not options:
            await matcher.finish("当前没有可修改时间的推送。")

        state[PUSH_TIME_OPTIONS_KEY] = options
        session_id, version = PUSH_TIME_FLOW.begin(event, state, target_type)
        state[PUSH_TIME_CONVERSATION_KEY] = conversation

        await enter_prompt_loop(
            matcher,
            handlers=[handle_push_time_select],
            rule=PUSH_TIME_FLOW.rule(state, session_id, version, target_type),
            prompt=build_push_time_menu_prompt(conversation, options),
            queue_namespace=PUSH_TIME_FLOW.namespace,
            queue_reply_check=PUSH_TIME_FLOW.reply_check(
                session_id,
                target_type,
            ),
            queue_group_reply_check=lambda next_event: PUSH_TIME_FLOW.input_check(
                next_event,
                target_type,
            ),
        )

    async def handle_push_time_select(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        raw_options = state.get(PUSH_TIME_OPTIONS_KEY)
        if not isinstance(raw_options, list):
            await matcher.finish()
        options: list[PushTimeOption] = raw_options

        target_type = state.get(PUSH_TIME_FLOW.target_type_key)
        conversation = state.get(PUSH_TIME_CONVERSATION_KEY)
        if target_type not in {"private", "group"} or not isinstance(
            conversation,
            ConversationRef,
        ):
            await matcher.finish()
        selected = state.get(PUSH_TIME_SELECTED_KEY)
        text = event.get_plaintext().strip()
        if selected is None:
            await _handle_push_time_index(matcher, state, text, options)
            return
        if not isinstance(selected, int):
            state.pop(PUSH_TIME_SELECTED_KEY, None)
            await matcher.finish()

        await _handle_push_time_value(
            matcher,
            state,
            text,
            options,
            PushTimeValueContext(
                selected=selected,
                conversation=conversation,
                refresh_push_time_jobs=refresh_push_time_jobs,
                messaging=messaging,
            ),
        )

    return handle_push_time_menu


async def _handle_push_time_index(
    matcher: Matcher,
    state: T_State,
    text: str,
    options: list[PushTimeOption],
) -> None:
    if text == "0":
        await matcher.finish("已退出。")
    index = int(text)
    if index < 1 or index > len(options):
        await PUSH_TIME_FLOW.reject(
            matcher,
            state,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )
    option = options[index - 1]
    state[PUSH_TIME_SELECTED_KEY] = index - 1
    await PUSH_TIME_FLOW.reject(
        matcher,
        state,
        push_time_value_prompt(option),
        selection=False,
        replace_menu_anchor=True,
    )


async def _handle_push_time_value(
    matcher: Matcher,
    state: T_State,
    text: str,
    options: list[PushTimeOption],
    context: PushTimeValueContext,
) -> None:
    selected_index = context.selected
    if selected_index < 0 or selected_index >= len(options):
        state.pop(PUSH_TIME_SELECTED_KEY, None)
        await PUSH_TIME_FLOW.reject(
            matcher,
            state,
            build_push_time_menu_prompt(context.conversation, options),
            replace_menu_anchor=True,
        )

    if text == "0":
        await matcher.finish("已退出。")

    option = options[selected_index]
    try:
        normalized = normalize_push_time_input(option, text)
    except ValueError as e:
        await PUSH_TIME_FLOW.reject(matcher, state, str(e), selection=False)
        return

    result_message = context.messaging.update_push_time(
        conversation=context.conversation,
        option=option,
        value=normalized,
    )

    await context.refresh_push_time_jobs(option)
    state.pop(PUSH_TIME_SELECTED_KEY, None)
    refreshed_options = context.messaging.push_time_options(
        context.conversation,
    )
    state[PUSH_TIME_OPTIONS_KEY] = refreshed_options
    prompt = (
        f"{result_message}\n\n"
        f"{build_push_time_menu_prompt(context.conversation, refreshed_options)}"
    )
    await PUSH_TIME_FLOW.reject(
        matcher,
        state,
        prompt,
        replace_menu_anchor=True,
    )
