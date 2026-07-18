from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.shared.messaging import message_event_target
from ironsbot.utils.matcher import enter_prompt_loop

from .matcher_rules import is_group_push_subscription_manager
from .push_management_runtime import (
    PUSH_SUBSCRIPTION_FLOW,
    PUSH_SUBSCRIPTION_OPTIONS_KEY,
    PUSH_SUBSCRIPTION_TARGET_ID_KEY,
)
from .push_subscription import (
    build_messaging_push_subscription_menu_prompt,
    build_messaging_push_subscription_options,
)
from .runtime_service import (  # noqa: TC001 - NoneBot resolves handler annotations
    MessagingResources,
)

if TYPE_CHECKING:
    from ironsbot.shared.messaging.push_subscription_models import (
        PushSubscriptionOption,
        PushTargetType,
    )


async def handle_push_subscription_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingResources,
) -> None:
    target_type, target_id, _ = message_event_target(event)
    read_only = isinstance(event, GroupMessageEvent) and not (
        is_group_push_subscription_manager(event)
    )
    options = build_messaging_push_subscription_options(
        target_type,
        target_id,
        config=messaging.config,
        store=messaging.store,
    )
    if not options:
        await matcher.finish("当前没有可管理的推送订阅。")

    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = options
    session_id, version = PUSH_SUBSCRIPTION_FLOW.begin(
        event,
        state,
        target_type,
    )
    state[PUSH_SUBSCRIPTION_TARGET_ID_KEY] = target_id

    await enter_prompt_loop(
        matcher,
        handlers=[
            partial(
                handle_push_subscription_select,
                messaging=messaging,
            )
        ],
        rule=PUSH_SUBSCRIPTION_FLOW.rule(
            session_id,
            version,
            target_type,
        ),
        prompt=build_messaging_push_subscription_menu_prompt(
            target_type,
            options,
            read_only=read_only,
        ),
    )


async def handle_push_subscription_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingResources,
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
        await PUSH_SUBSCRIPTION_FLOW.reject(
            matcher,
            state,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )

    option = options[index - 1]
    target_type = state.get(PUSH_SUBSCRIPTION_FLOW.target_type_key)
    target_id = state.get(PUSH_SUBSCRIPTION_TARGET_ID_KEY)
    if target_type not in {"private", "group"} or not isinstance(target_id, int):
        await matcher.finish()
    target_type = cast("PushTargetType", target_type)

    if target_type == "group" and (
        not isinstance(event, GroupMessageEvent)
        or not is_group_push_subscription_manager(event)
    ):
        menu_prompt = build_messaging_push_subscription_menu_prompt(
            target_type,
            options,
            read_only=True,
        )
        prompt = (
            "普通群成员只能查看本群推送订阅，不能修改；需要群主或管理员操作。\n\n"
            f"{menu_prompt}"
        )
        await PUSH_SUBSCRIPTION_FLOW.reject(matcher, state, prompt)

    if messaging.store.is_target_unsubscribed(target_type, target_id, option.key):
        messaging.store.restore_target(target_type, target_id, option.key)
        result_message = f"已恢复订阅：{option.label}。"
    else:
        messaging.store.unsubscribe_target(
            target_type,
            target_id,
            option.key,
            option.feature,
        )
        result_message = f"已退订：{option.label}。"

    refreshed_options = build_messaging_push_subscription_options(
        target_type,
        target_id,
        config=messaging.config,
        store=messaging.store,
    )
    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = refreshed_options
    menu_prompt = build_messaging_push_subscription_menu_prompt(
        target_type,
        refreshed_options,
    )
    prompt = f"{result_message}\n\n{menu_prompt}"
    await PUSH_SUBSCRIPTION_FLOW.reject(matcher, state, prompt)


__all__ = [
    "handle_push_subscription_menu",
    "handle_push_subscription_select",
]
