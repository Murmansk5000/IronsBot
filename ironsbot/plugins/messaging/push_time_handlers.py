from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from ironsbot.shared.messaging import event_conversation_session_id
from ironsbot.utils.matcher import enter_prompt_loop, prompt_session_manager

from .push_management_runtime import (
    PUSH_TIME_NAMESPACE,
    PUSH_TIME_OPTIONS_KEY,
    PUSH_TIME_SELECTED_KEY,
    PUSH_TIME_SESSION_KEY,
    PUSH_TIME_TARGET_ID_KEY,
    PUSH_TIME_TARGET_TYPE_KEY,
    PUSH_TIME_VERSION_KEY,
    _normalize_push_time_input,
    _push_subscription_store,
    _push_time_menu_prompt,
    _push_time_options,
    _push_time_selection_rule,
    _push_time_value_prompt,
    _reject_push_time_input,
    _reject_push_time_selection,
    _target_type_and_id,
)
from .push_time import PushTimeOption

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.shared.messaging.push_subscription_models import PushTargetType

RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


@dataclass
class PushTimeHandlerContext:
    refresh_push_time_jobs: RefreshPushTimeJobs | None = None


@dataclass(frozen=True)
class PushTimeValueContext:
    selected: int
    target_type: PushTargetType
    target_id: int


_handler_context = PushTimeHandlerContext()


def configure_push_time_handlers(refresh_push_time_jobs: RefreshPushTimeJobs) -> None:
    _handler_context.refresh_push_time_jobs = refresh_push_time_jobs


async def handle_push_time_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    target_type, target_id = _target_type_and_id(event)
    options = _push_time_options(target_type, target_id)
    if not options:
        await matcher.finish("当前没有可修改时间的推送。")

    state[PUSH_TIME_OPTIONS_KEY] = options
    session_id = event_conversation_session_id(PUSH_TIME_NAMESPACE, event)
    version = prompt_session_manager.acquire(session_id)
    state[PUSH_TIME_SESSION_KEY] = session_id
    state[PUSH_TIME_TARGET_ID_KEY] = target_id
    state[PUSH_TIME_TARGET_TYPE_KEY] = target_type
    state[PUSH_TIME_VERSION_KEY] = version

    await enter_prompt_loop(
        matcher,
        handlers=[handle_push_time_select],
        rule=_push_time_selection_rule(session_id, version, target_type),
        prompt=_push_time_menu_prompt(target_type, options),
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

    target_type = state.get(PUSH_TIME_TARGET_TYPE_KEY)
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
        ),
    )


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
        await _reject_push_time_selection(
            matcher,
            state,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )
    option = options[index - 1]
    state[PUSH_TIME_SELECTED_KEY] = index - 1
    await _reject_push_time_input(
        matcher,
        state,
        _push_time_value_prompt(option),
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
        await _reject_push_time_selection(
            matcher,
            state,
            _push_time_menu_prompt(context.target_type, options),
        )

    if text == "0":
        await matcher.finish("已退出。")

    option = options[selected_index]
    store = _push_subscription_store()
    try:
        normalized = _normalize_push_time_input(option, text)
    except ValueError as e:
        await _reject_push_time_input(matcher, state, str(e))
        return

    if normalized is None:
        store.clear_time_preference(
            context.target_type,
            context.target_id,
            option.key,
            option.preference_type,
        )
        result_message = f"已恢复默认：{option.label}。"
    else:
        store.set_time_preference(
            context.target_type,
            context.target_id,
            option.key,
            option.preference_type,
            normalized,
        )
        result_message = f"已设置：{option.label} -> {normalized}。"

    if _handler_context.refresh_push_time_jobs is not None:
        await _handler_context.refresh_push_time_jobs(option)
    state.pop(PUSH_TIME_SELECTED_KEY, None)
    refreshed_options = _push_time_options(context.target_type, context.target_id)
    state[PUSH_TIME_OPTIONS_KEY] = refreshed_options
    prompt = (
        f"{result_message}\n\n"
        f"{_push_time_menu_prompt(context.target_type, refreshed_options)}"
    )
    await _reject_push_time_selection(matcher, state, prompt)


__all__ = [
    "configure_push_time_handlers",
    "handle_push_time_menu",
    "handle_push_time_select",
]
