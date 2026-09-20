from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.platform import ConversationRef
from ironsbot.integrations.onebot.matchers import bind_async, enter_prompt_loop
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.messaging.service import (  # noqa: TC001
    MessagingService,
)

from .matcher_rules import is_group_push_subscription_manager
from .push_management_runtime import (
    PUSH_SUBSCRIPTION_CONVERSATION_KEY,
    PUSH_SUBSCRIPTION_FLOW,
    PUSH_SUBSCRIPTION_OPTIONS_KEY,
    OneBotConversationKind,
)

if TYPE_CHECKING:
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionOption,
    )


async def handle_push_subscription_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
) -> None:
    conversation = message_input_context(event).message.conversation
    if conversation.kind not in {"private", "group"}:
        await matcher.finish()
    target_type = cast("OneBotConversationKind", conversation.kind)
    read_only = isinstance(event, GroupMessageEvent) and not (
        is_group_push_subscription_manager(messaging, event)
    )
    options, prompt = await messaging.prepared_subscription_menu(
        conversation,
        read_only=read_only,
    )
    if not options:
        await matcher.finish("当前没有可管理的推送订阅。")

    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = options
    session_id, version = PUSH_SUBSCRIPTION_FLOW.begin(
        event,
        state,
        target_type,
    )
    state[PUSH_SUBSCRIPTION_CONVERSATION_KEY] = conversation

    await enter_prompt_loop(
        matcher,
        handlers=[
            bind_async(
                handle_push_subscription_select,
                messaging=messaging,
            )
        ],
        rule=PUSH_SUBSCRIPTION_FLOW.rule(
            state,
            session_id,
            version,
            target_type,
        ),
        prompt=prompt,
        queue_namespace=PUSH_SUBSCRIPTION_FLOW.namespace,
        queue_reply_check=PUSH_SUBSCRIPTION_FLOW.reply_check(
            session_id,
            target_type,
        ),
        queue_group_reply_check=lambda next_event: PUSH_SUBSCRIPTION_FLOW.input_check(
            next_event,
            target_type,
        ),
    )


async def handle_push_subscription_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    messaging: MessagingService,
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
    conversation = state.get(PUSH_SUBSCRIPTION_CONVERSATION_KEY)
    if target_type not in {"private", "group"} or not isinstance(
        conversation,
        ConversationRef,
    ):
        await matcher.finish()
    if conversation.kind == "group" and (
        not isinstance(event, GroupMessageEvent)
        or not is_group_push_subscription_manager(messaging, event)
    ):
        _, menu_prompt = messaging.subscription_menu(
            conversation,
            read_only=True,
        )
        prompt = (
            "普通群成员只能查看本群推送订阅，不能修改；需要群主或管理员操作。\n\n"
            f"{menu_prompt}"
        )
        await PUSH_SUBSCRIPTION_FLOW.reject(
            matcher,
            state,
            prompt,
            replace_menu_anchor=True,
        )

    if submenu := messaging.subscription_submenu(
        conversation,
        option,
        read_only=False,
    ):
        submenu_options, submenu_prompt = submenu
        state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = submenu_options
        await PUSH_SUBSCRIPTION_FLOW.reject(
            matcher,
            state,
            submenu_prompt,
            replace_menu_anchor=True,
        )

    result_message = messaging.toggle_subscription(
        conversation,
        option,
    )
    refreshed_options, menu_prompt = messaging.subscription_menu(
        conversation,
    )
    state[PUSH_SUBSCRIPTION_OPTIONS_KEY] = refreshed_options
    prompt = f"{result_message}\n\n{menu_prompt}"
    await PUSH_SUBSCRIPTION_FLOW.reject(
        matcher,
        state,
        prompt,
        replace_menu_anchor=True,
    )
