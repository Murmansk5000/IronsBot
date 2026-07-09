from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.shared.messaging import event_conversation_session_id
from ironsbot.utils.matcher import enter_prompt_loop, prompt_session_manager

from .matcher_rules import is_group_push_subscription_manager
from .push_management_runtime import (
    PUSH_SUBSCRIPTION_NAMESPACE,
    PUSH_SUBSCRIPTION_OPTIONS_KEY,
    PUSH_SUBSCRIPTION_SESSION_KEY,
    PUSH_SUBSCRIPTION_TARGET_ID_KEY,
    PUSH_SUBSCRIPTION_TARGET_TYPE_KEY,
    PUSH_SUBSCRIPTION_VERSION_KEY,
    PUSH_TIME_NAMESPACE,
    PUSH_TIME_OPTIONS_KEY,
    PUSH_TIME_SELECTED_KEY,
    PUSH_TIME_SESSION_KEY,
    PUSH_TIME_TARGET_ID_KEY,
    PUSH_TIME_TARGET_TYPE_KEY,
    PUSH_TIME_VERSION_KEY,
    _normalize_push_time_input,
    _push_subscription_menu_prompt,
    _push_subscription_options,
    _push_subscription_selection_rule,
    _push_subscription_store,
    _push_time_menu_prompt,
    _push_time_options,
    _push_time_selection_rule,
    _push_time_value_prompt,
    _reject_push_subscription_selection,
    _reject_push_time_input,
    _reject_push_time_selection,
    _target_type_and_id,
)
from .push_time import PushTimeOption

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscriptions import (
        PushSubscriptionOption,
        PushTargetType,
    )

RefreshPushTimeJobs = Callable[[PushTimeOption], Awaitable[None]]


@dataclass
class PushManagementHandlerContext:
    refresh_push_time_jobs: RefreshPushTimeJobs | None = None


@dataclass(frozen=True)
class PushTimeValueContext:
    selected: int
    target_type: PushTargetType
    target_id: int


_handler_context = PushManagementHandlerContext()


def register_push_management_handlers(
    *,
    push_subscription_matcher: type[Matcher],
    push_time_matcher: type[Matcher],
    refresh_push_time_jobs: RefreshPushTimeJobs,
) -> None:
    _handler_context.refresh_push_time_jobs = refresh_push_time_jobs
    push_subscription_matcher.handle()(handle_push_subscription_menu)
    push_time_matcher.handle()(handle_push_time_menu)


async def handle_push_subscription_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    target_type, target_id = _target_type_and_id(event)
    read_only = isinstance(event, GroupMessageEvent) and not (
        is_group_push_subscription_manager(event)
    )
    options = _push_subscription_options(
        target_type,
        target_id,
    )
    if not options:
        await matcher.finish("当前没有可管理的推送订阅。")

    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = options
    session_id = event_conversation_session_id(
        PUSH_SUBSCRIPTION_NAMESPACE,
        event,
    )
    version = prompt_session_manager.acquire(session_id)
    state[PUSH_SUBSCRIPTION_SESSION_KEY] = session_id
    state[PUSH_SUBSCRIPTION_TARGET_ID_KEY] = target_id
    state[PUSH_SUBSCRIPTION_TARGET_TYPE_KEY] = target_type
    state[PUSH_SUBSCRIPTION_VERSION_KEY] = version

    await enter_prompt_loop(
        matcher,
        handlers=[handle_push_subscription_select],
        rule=_push_subscription_selection_rule(
            session_id,
            version,
            target_type,
        ),
        prompt=_push_subscription_menu_prompt(
            target_type,
            options,
            read_only=read_only,
        ),
    )


async def handle_push_subscription_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    raw_options = state.get(PUSH_SUBSCRIPTION_OPTIONS_KEY)
    if not isinstance(raw_options, list):
        await matcher.finish()
    options: list[PushSubscriptionOption] = raw_options

    text = event.get_plaintext().strip()
    if text == "0":
        await matcher.finish("已退出。")
    index = int(text)
    if index < 1 or index > len(options):
        await _reject_push_subscription_selection(
            matcher,
            state,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )

    option = options[index - 1]
    target_type = state.get(PUSH_SUBSCRIPTION_TARGET_TYPE_KEY)
    target_id = state.get(PUSH_SUBSCRIPTION_TARGET_ID_KEY)
    if target_type not in {"private", "group"} or not isinstance(target_id, int):
        await matcher.finish()
    target_type = cast("PushTargetType", target_type)

    if target_type == "group" and (
        not isinstance(event, GroupMessageEvent)
        or not is_group_push_subscription_manager(event)
    ):
        menu_prompt = _push_subscription_menu_prompt(
            target_type,
            options,
            read_only=True,
        )
        prompt = (
            "普通群成员只能查看本群推送订阅，不能修改；需要群主或管理员操作。\n\n"
            f"{menu_prompt}"
        )
        await _reject_push_subscription_selection(matcher, state, prompt)

    store = _push_subscription_store()
    if store.is_target_unsubscribed(target_type, target_id, option.key):
        store.restore_target(target_type, target_id, option.key)
        result_message = f"已恢复订阅：{option.label}。"
    else:
        store.unsubscribe_target(target_type, target_id, option.key, option.feature)
        result_message = f"已退订：{option.label}。"

    refreshed_options = _push_subscription_options(target_type, target_id)
    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = refreshed_options
    prompt = (
        f"{result_message}\n\n"
        f"{_push_subscription_menu_prompt(target_type, refreshed_options)}"
    )
    await _reject_push_subscription_selection(matcher, state, prompt)


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
    "handle_push_subscription_menu",
    "handle_push_subscription_select",
    "handle_push_time_menu",
    "handle_push_time_select",
    "register_push_management_handlers",
]
