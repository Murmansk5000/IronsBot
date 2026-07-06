from typing import Any, cast

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
from ironsbot.shared.messaging.push_subscriptions import (
    BUILTIN_PUSH_OPTIONS,
    PushSubscriptionOption,
    PushTargetType,
    PushUnsubscribeStore,
    build_push_subscription_menu,
    build_schedule_subscription_options,
    group_schedule_key,
    private_schedule_key,
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

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"
PUSH_SUBSCRIPTION_OPTIONS_KEY = "_message_push_subscription_options"
PUSH_SUBSCRIPTION_SESSION_KEY = "_message_push_subscription_session"
PUSH_SUBSCRIPTION_TARGET_ID_KEY = "_message_push_subscription_target_id"
PUSH_SUBSCRIPTION_TARGET_TYPE_KEY = "_message_push_subscription_target_type"
PUSH_SUBSCRIPTION_VERSION_KEY = "_message_push_subscription_version"
PUSH_SUBSCRIPTION_NAMESPACE = "message_push_subscription"
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


def _is_group_push_subscription_manager(event: GroupMessageEvent) -> bool:
    role = getattr(event.sender, "role", None)
    return role in {"owner", "admin"}


async def _match_push_subscription_command(
    event: MessageEvent,
    _state: T_State,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    config = get_message_config().push_unsubscribe
    if isinstance(event, GroupMessageEvent) and not _is_group_push_subscription_manager(
        event
    ):
        return False

    text = event.get_plaintext()
    if command_text_matches(text, config.commands):
        return True
    return command_text_matches(text, config.restore_commands)


def _message_subscription_priority() -> int:
    return max(get_matcher_priority("message_commands", 4) - 1, 0)


private_command_matcher = on_message(
    rule=Rule(_match_private_command) & no_reply(),
    priority=get_matcher_priority("message_commands", 4),
    block=True,
)

push_subscription_matcher = on_message(
    rule=Rule(_match_push_subscription_command) & no_reply(),
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


def _push_subscription_store() -> PushUnsubscribeStore:
    return PushUnsubscribeStore(get_message_config().push_unsubscribe.data_path)


def _target_type_and_id(event: MessageEvent) -> tuple[PushTargetType, int]:
    if isinstance(event, GroupMessageEvent):
        return "group", int(event.group_id)
    return "private", int(event.user_id)


def _eligible_target_ids_by_feature(
    target_type: PushTargetType,
    features: set[str],
) -> dict[str, set[int]]:
    if target_type == "group":
        return {
            feature: set(groups_for_feature(feature))
            for feature in features
        }

    return {
        feature: set(users_with_superusers(users_for_feature(feature)))
        for feature in features
    }


def _builtin_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    unsubscribed = store.target_unsubscribed_keys(target_type, target_id)
    eligible = _eligible_target_ids_by_feature(
        target_type,
        {option.feature for option in BUILTIN_PUSH_OPTIONS},
    )
    options: list[PushSubscriptionOption] = []
    for option in BUILTIN_PUSH_OPTIONS:
        if target_id not in eligible.get(option.feature, set()):
            continue
        is_unsubscribed = option.key in unsubscribed
        options.append(
            PushSubscriptionOption(
                key=option.key,
                label=option.label,
                feature=option.feature,
                unsubscribed=is_unsubscribed,
            )
        )
    return options


def _schedule_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> list[PushSubscriptionOption]:
    config = get_message_config()
    tasks = (
        config.group_schedules
        if target_type == "group"
        else config.private_schedules
    )
    features = {task.feature for task in tasks if task.enabled}
    return build_schedule_subscription_options(
        target_type=target_type,
        target_id=target_id,
        tasks=tasks,
        eligible_target_ids_for_feature=_eligible_target_ids_by_feature(
            target_type,
            features,
        ),
        store=store,
    )


def _push_subscription_options(
    target_type: PushTargetType,
    target_id: int,
) -> list[PushSubscriptionOption]:
    store = _push_subscription_store()
    from ironsbot.services.bilibili.state import bili_push_subscription_options

    return [
        *bili_push_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
        *_builtin_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
        *_schedule_subscription_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        ),
    ]


def _push_subscription_menu_title(target_type: PushTargetType) -> str:
    scope = "本群" if target_type == "group" else "私聊"
    return f"请选择要切换的{scope}推送订阅："


def _push_subscription_menu_prompt(
    target_type: PushTargetType,
    options: list[PushSubscriptionOption],
) -> str:
    return build_push_subscription_menu(
        title=_push_subscription_menu_title(target_type),
        options=options,
    )


def _push_subscription_selection_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: MessageEvent) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if (
            event_conversation_session_id(
                PUSH_SUBSCRIPTION_NAMESPACE,
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


async def _reject_push_subscription_selection(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_SUBSCRIPTION_SESSION_KEY)
    version = state.get(PUSH_SUBSCRIPTION_VERSION_KEY)
    target_type = state.get(PUSH_SUBSCRIPTION_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_subscription_selection_rule(
            session_id,
            version,
            target_type,
        ),
        prompt=prompt,
    )


@push_subscription_matcher.handle()
async def handle_push_subscription_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    target_type, target_id = _target_type_and_id(event)
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
        rule=_push_subscription_selection_rule(session_id, version, target_type),
        prompt=_push_subscription_menu_prompt(target_type, options),
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

    await send_broadcast_message(
        append_fire_manual_ad_text(task.message),
        private_user_ids=private_user_ids,
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
        subscription_key=private_schedule_key(index, task),
    )


async def _send_group_schedule(
    task: GroupScheduledMessageAction,
    index: int = 1,
) -> None:
    await send_broadcast_message(
        task.message,
        group_ids=groups_for_feature(task.feature),
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=append_fire_manual_ad_for_group,
        subscription_key=group_schedule_key(index, task),
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
        kwargs={"task": task, "index": index},
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
