from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.shared.messaging import message_event_target
from ironsbot.shared.messaging.push_subscription_models import PushTargetType
from ironsbot.utils.matcher import enter_prompt_loop

from .push_management_runtime import (
    PUSH_TIME_FLOW,
    PUSH_TIME_OPTIONS_KEY,
    PUSH_TIME_SELECTED_KEY,
    PUSH_TIME_TARGET_ID_KEY,
)
from .push_time import (
    PushTimeOption,
    build_push_time_menu_prompt,
    build_push_time_options,
    normalize_push_time_input,
    push_time_value_prompt,
)

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscription_store import (
        PushUnsubscribeStore,
    )

    from .runtime_service import MessagingResources

RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


@dataclass(frozen=True)
class PushTimeValueContext:
    selected: int
    target_type: PushTargetType
    target_id: int
    refresh_push_time_jobs: RefreshPushTimeJobs
    store: PushUnsubscribeStore
    options_for: BuildPushTimeOptions


PushTimeHandler = Callable[[Matcher, MessageEvent, T_State], Awaitable[None]]
BuildPushTimeOptions = Callable[[PushTargetType, int], list[PushTimeOption]]


def build_push_time_menu_handler(
    refresh_push_time_jobs: RefreshPushTimeJobs,
    messaging: MessagingResources,
) -> PushTimeHandler:
    def options_for(
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushTimeOption]:
        return build_push_time_options(
            target_type,
            target_id,
            message_config=messaging.config,
            activity_config=messaging.activity,
            store=messaging.store,
        )

    async def handle_push_time_menu(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        target_type, target_id, _ = message_event_target(event)
        options = options_for(target_type, target_id)
        if not options:
            await matcher.finish("当前没有可修改时间的推送。")

        state[PUSH_TIME_OPTIONS_KEY] = options
        session_id, version = PUSH_TIME_FLOW.begin(event, state, target_type)
        state[PUSH_TIME_TARGET_ID_KEY] = target_id

        await enter_prompt_loop(
            matcher,
            handlers=[handle_push_time_select],
            rule=PUSH_TIME_FLOW.rule(session_id, version, target_type),
            prompt=build_push_time_menu_prompt(target_type, options),
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
        target_id = state.get(PUSH_TIME_TARGET_ID_KEY)
        if target_type not in {"private", "group"} or not isinstance(target_id, int):
            await matcher.finish()
        target_type = cast("PushTargetType", target_type)

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
                target_type=target_type,
                target_id=target_id,
                refresh_push_time_jobs=refresh_push_time_jobs,
                store=messaging.store,
                options_for=options_for,
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
            build_push_time_menu_prompt(context.target_type, options),
        )

    if text == "0":
        await matcher.finish("已退出。")

    option = options[selected_index]
    try:
        normalized = normalize_push_time_input(option, text)
    except ValueError as e:
        await PUSH_TIME_FLOW.reject(matcher, state, str(e), selection=False)
        return

    if normalized is None:
        context.store.clear_time_preference(
            context.target_type,
            context.target_id,
            option.key,
            option.preference_type,
        )
        result_message = f"已恢复默认：{option.label}。"
    else:
        context.store.set_time_preference(
            context.target_type,
            context.target_id,
            option.key,
            option.preference_type,
            normalized,
        )
        result_message = f"已设置：{option.label} -> {normalized}。"

    await context.refresh_push_time_jobs(option)
    state.pop(PUSH_TIME_SELECTED_KEY, None)
    refreshed_options = context.options_for(context.target_type, context.target_id)
    state[PUSH_TIME_OPTIONS_KEY] = refreshed_options
    prompt = (
        f"{result_message}\n\n"
        f"{build_push_time_menu_prompt(context.target_type, refreshed_options)}"
    )
    await PUSH_TIME_FLOW.reject(matcher, state, prompt)
