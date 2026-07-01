from typing import Any

from nonebot import get_driver, on_message, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.shared.features import (
    groups_for_feature,
    is_group_feature_allowed,
    is_private_feature_allowed,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    command_text_matches,
    event_conversation_session_id,
    event_sender_at_user_ids,
    finish_matcher_message,
    send_broadcast_message,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.shared.promotions import (
    append_fire_manual_ad_for_group,
    append_fire_manual_ad_text,
)
from ironsbot.utils.matcher import (
    enter_prompt_loop,
    prompt_session_manager,
    reject_with_rule,
)
from ironsbot.utils.rule import no_reply

from .config import (
    GroupScheduledMessageAction,
    PrivateCommandMessageAction,
    PrivateScheduledMessageAction,
    get_message_config,
)
from .runtime_service import (
    build_schedule_job_id,
    build_schedule_trigger_kwargs,
    find_command_action,
)
from .unsubscribe import (
    PrivatePushUnsubscribeStore,
    PrivateScheduleSubscriptionOption,
    append_private_unsubscribe_hint,
    build_private_schedule_menu,
    build_private_schedule_options,
    private_schedule_key,
)

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"
PRIVATE_SUBSCRIPTION_MODE_KEY = "_message_private_subscription_mode"
PRIVATE_SUBSCRIPTION_OPTIONS_KEY = "_message_private_subscription_options"
PRIVATE_SUBSCRIPTION_SESSION_KEY = "_message_private_subscription_session"
PRIVATE_SUBSCRIPTION_VERSION_KEY = "_message_private_subscription_version"
PRIVATE_SUBSCRIPTION_NAMESPACE = "message_private_subscription"
PRIVATE_SUBSCRIPTION_UNSUBSCRIBE_MODE = "unsubscribe"
PRIVATE_SUBSCRIPTION_RESTORE_MODE = "restore"
MESSAGE_PLUGIN_NAME = "message"
_messaging_runtime_state = {"registered": False}


def _private_action_allowed(
    event: PrivateMessageEvent,
    action: PrivateCommandMessageAction,
) -> bool:
    return is_private_feature_allowed(
        event.user_id,
        action.feature,
    )


async def _match_private_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.private_commands,
        is_allowed=lambda candidate: _private_action_allowed(event, candidate),
    )
    if action is not None:
        state[PRIVATE_ACTION_KEY] = action
        return True

    return False


async def _match_group_command(event: MessageEvent, state: T_State) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    text = event.get_plaintext()
    config = get_message_config()
    action = find_command_action(
        text,
        config.group_commands,
        is_allowed=lambda candidate: is_group_feature_allowed(
            event.user_id,
            event.group_id,
            candidate.feature,
        ),
    )
    if action is not None:
        state[GROUP_ACTION_KEY] = action
        return True

    return False


async def _match_private_subscription_command(
    event: MessageEvent,
    state: T_State,
) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    config = get_message_config().private_unsubscribe
    if not config.enabled:
        return False

    text = event.get_plaintext()
    if command_text_matches(text, config.commands):
        state[PRIVATE_SUBSCRIPTION_MODE_KEY] = PRIVATE_SUBSCRIPTION_UNSUBSCRIBE_MODE
        return True
    if command_text_matches(text, config.restore_commands):
        state[PRIVATE_SUBSCRIPTION_MODE_KEY] = PRIVATE_SUBSCRIPTION_RESTORE_MODE
        return True
    return False


def _message_subscription_priority() -> int:
    return max(get_matcher_priority("message_commands", 4) - 1, 0)


private_command_matcher = on_message(
    rule=Rule(_match_private_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)

private_subscription_matcher = on_message(
    rule=Rule(_match_private_subscription_command) & no_reply(),
    priority=_message_subscription_priority(),
    block=True,
)

group_command_matcher = on_message(
    rule=Rule(_match_group_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)


class MessagingPlugin:
    name = MESSAGE_PLUGIN_NAME
    feature = "text"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "private_command" and isinstance(
            event,
            PrivateMessageEvent,
        ):
            await self._handle_private_command(event, context)
            return

        if context.action == "group_command" and isinstance(event, GroupMessageEvent):
            await self._handle_group_command(event, context)
            return

    async def _handle_private_command(
        self,
        event: PrivateMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[PRIVATE_ACTION_KEY]
        await finish_matcher_message(
            context.matcher or private_command_matcher,
            action.message,
            event=event,
        )

    async def _handle_group_command(
        self,
        event: GroupMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[GROUP_ACTION_KEY]
        at_user_ids = [
            *event_sender_at_user_ids(event),
            *action.at_user_ids,
        ]
        await finish_matcher_message(
            context.matcher or group_command_matcher,
            action.message,
            at_user_ids=at_user_ids,
            event=event,
        )


register_plugin(MessagingPlugin())


@private_command_matcher.handle()
async def handle_private_command(
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=private_command_matcher,
        state=state,
        action="private_command",
    )


def _private_subscription_store() -> PrivatePushUnsubscribeStore:
    return PrivatePushUnsubscribeStore(
        get_message_config().private_unsubscribe.data_path
    )


def _private_schedule_eligible_user_ids_by_feature() -> dict[str, set[int]]:
    tasks = get_message_config().private_schedules
    features = {task.feature for task in tasks if task.enabled}
    return {
        feature: set(users_with_superusers(users_for_feature(feature)))
        for feature in features
    }


def _private_subscription_options(
    user_id: int,
    *,
    include_unsubscribed: bool,
) -> list[PrivateScheduleSubscriptionOption]:
    return build_private_schedule_options(
        user_id=user_id,
        tasks=get_message_config().private_schedules,
        eligible_user_ids_for_feature=_private_schedule_eligible_user_ids_by_feature(),
        store=_private_subscription_store(),
        include_unsubscribed=include_unsubscribed,
    )


def _private_subscription_selection_rule(session_id: str, version: int) -> Rule:
    def _check(next_event: MessageEvent) -> bool:
        if not isinstance(next_event, PrivateMessageEvent):
            return False
        if (
            event_conversation_session_id(
                PRIVATE_SUBSCRIPTION_NAMESPACE,
                next_event,
            )
            != session_id
        ):
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return next_event.get_plaintext().strip().isdigit()

    return prompt_session_manager.make_rule(session_id, version, _check)


async def _reject_private_subscription_selection(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PRIVATE_SUBSCRIPTION_SESSION_KEY)
    version = state.get(PRIVATE_SUBSCRIPTION_VERSION_KEY)
    if not isinstance(session_id, str) or not isinstance(version, int):
        await matcher.finish(prompt)

    await reject_with_rule(
        matcher,
        _private_subscription_selection_rule(session_id, version),
        prompt=prompt,
    )


@private_subscription_matcher.handle()
async def handle_private_subscription_menu(
    matcher: Matcher,
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    mode = state.get(PRIVATE_SUBSCRIPTION_MODE_KEY)
    include_unsubscribed = mode == PRIVATE_SUBSCRIPTION_RESTORE_MODE
    options = _private_subscription_options(
        event.user_id,
        include_unsubscribed=include_unsubscribed,
    )
    if not options:
        if include_unsubscribed:
            await matcher.finish("当前没有可恢复的私聊定时推送。")
        await matcher.finish("当前没有可退订的私聊定时推送。")

    state[PRIVATE_SUBSCRIPTION_OPTIONS_KEY] = options
    session_id = event_conversation_session_id(
        PRIVATE_SUBSCRIPTION_NAMESPACE,
        event,
    )
    version = prompt_session_manager.acquire(session_id)
    state[PRIVATE_SUBSCRIPTION_SESSION_KEY] = session_id
    state[PRIVATE_SUBSCRIPTION_VERSION_KEY] = version

    title = (
        "请选择要恢复订阅的私聊推送："
        if include_unsubscribed
        else "请选择要退订的私聊推送："
    )
    await enter_prompt_loop(
        matcher,
        handlers=[handle_private_subscription_select],
        rule=_private_subscription_selection_rule(session_id, version),
        prompt=build_private_schedule_menu(title=title, options=options),
    )


async def handle_private_subscription_select(
    matcher: Matcher,
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    raw_options = state.get(PRIVATE_SUBSCRIPTION_OPTIONS_KEY)
    if not isinstance(raw_options, list):
        await matcher.finish()
    options: list[PrivateScheduleSubscriptionOption] = raw_options

    text = event.get_plaintext().strip()
    if text == "0":
        await matcher.finish("已退出。")
    index = int(text)
    if index < 1 or index > len(options):
        await _reject_private_subscription_selection(
            matcher,
            state,
            "⚠️ 序号超出范围，请重新输入；输入 0 退出。",
        )

    option = options[index - 1]
    mode = state.get(PRIVATE_SUBSCRIPTION_MODE_KEY)
    store = _private_subscription_store()
    if mode == PRIVATE_SUBSCRIPTION_RESTORE_MODE:
        store.restore(event.user_id, option.key)
        await matcher.finish(f"已恢复订阅：{option.label}。")

    store.unsubscribe(event.user_id, option.key, option.feature)
    await matcher.finish(f"已退订：{option.label}。\n发送“订阅”可恢复。")


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=group_command_matcher,
        state=state,
        action="group_command",
    )


async def _send_private_schedule(
    task: PrivateScheduledMessageAction,
    index: int = 1,
) -> None:
    private_user_ids = users_with_superusers(users_for_feature(task.feature))
    unsubscribe_config = get_message_config().private_unsubscribe
    if unsubscribe_config.enabled:
        private_user_ids = PrivatePushUnsubscribeStore(
            unsubscribe_config.data_path
        ).filter_subscribed_user_ids(
            private_user_ids,
            private_schedule_key(index, task),
        )

    await send_broadcast_message(
        append_private_unsubscribe_hint(
            append_fire_manual_ad_text(task.message),
            unsubscribe_config,
        ),
        private_user_ids=private_user_ids,
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
    )


async def _send_group_schedule(task: GroupScheduledMessageAction) -> None:
    await send_broadcast_message(
        task.message,
        group_ids=groups_for_feature(task.feature),
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=append_fire_manual_ad_for_group,
    )


def _register_private_schedule(
    scheduler: Any,
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    scheduler.add_job(
        _send_private_schedule,
        "cron",
        kwargs={"task": task, "index": index},
        id=build_schedule_job_id("private_schedule", index, task.id),
        replace_existing=True,
        **build_schedule_trigger_kwargs(task),
    )


def _register_group_schedule(
    scheduler: Any,
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    if not task.enabled:
        return

    scheduler.add_job(
        _send_group_schedule,
        "cron",
        kwargs={"task": task},
        id=build_schedule_job_id("group_schedule", index, task.id),
        replace_existing=True,
        **build_schedule_trigger_kwargs(task),
    )


async def register_message_schedules(scheduler: Any) -> None:
    config = get_message_config()
    for index, task in enumerate(config.private_schedules, start=1):
        _register_private_schedule(scheduler, index, task)

    for index, task in enumerate(config.group_schedules, start=1):
        _register_group_schedule(scheduler, index, task)


def _setup_messaging_runtime(driver: Any, scheduler: Any) -> None:
    if _messaging_runtime_state["registered"]:
        return

    @driver.on_startup
    async def _register_message_schedules_on_startup() -> None:
        await register_message_schedules(scheduler)

    _messaging_runtime_state["registered"] = True


def setup_messaging_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_messaging_runtime(get_driver(), scheduler)
