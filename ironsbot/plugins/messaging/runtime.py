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
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    command_text_matches,
    event_conversation_session_id,
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.shared.messaging.push_subscriptions import (
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
    PushTargetType,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.matcher import (
    enter_prompt_loop,
    prompt_session_manager,
)
from ironsbot.utils.rule import no_reply

from . import schedules as message_schedules
from .config import (
    PrivateCommandMessageAction,
    get_message_config,
)
from .push_management_runtime import (
    PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS,
    PUSH_SUBSCRIPTION_NAMESPACE,
    PUSH_SUBSCRIPTION_OPTIONS_KEY,
    PUSH_SUBSCRIPTION_SESSION_KEY,
    PUSH_SUBSCRIPTION_TARGET_ID_KEY,
    PUSH_SUBSCRIPTION_TARGET_TYPE_KEY,
    PUSH_SUBSCRIPTION_VERSION_KEY,
    PUSH_TIME_COMMANDS,
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
from .push_time import (
    PushTimeOption,
)
from .runtime_service import find_command_action

PRIVATE_ACTION_KEY = "_message_action_private"
GROUP_ACTION_KEY = "_message_action_group"

MESSAGE_PLUGIN_NAME = "message"
_messaging_runtime_state = {"registered": False, "scheduler": None}


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
    if is_superuser(int(event.user_id)):
        return True
    role = getattr(event.sender, "role", None)
    return role in {"owner", "admin"}


async def _match_push_subscription_command(
    event: MessageEvent,
    _state: T_State,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False

    config = get_message_config().push_unsubscribe

    text = event.get_plaintext()
    if command_text_matches(text, PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS):
        return True
    if command_text_matches(text, config.commands):
        return True
    return command_text_matches(text, config.restore_commands)


async def _match_push_time_command(
    event: MessageEvent,
    _state: T_State,
) -> bool:
    if not isinstance(event, (PrivateMessageEvent, GroupMessageEvent)):
        return False
    if isinstance(event, GroupMessageEvent) and not _is_group_push_subscription_manager(
        event
    ):
        return False
    return command_text_matches(event.get_plaintext(), PUSH_TIME_COMMANDS)


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

push_time_matcher = on_message(
    rule=Rule(_match_push_time_command) & no_reply(),
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


async def _refresh_push_time_jobs(option: PushTimeOption) -> None:
    if option.preference_type == CRON_TIME_PREFERENCE:
        await refresh_message_schedules()
        return

    from ironsbot.plugins.activity.runtime import schedule_activity_reminders

    await schedule_activity_reminders()


@push_subscription_matcher.handle()
async def handle_push_subscription_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    target_type, target_id = _target_type_and_id(event)
    read_only = isinstance(event, GroupMessageEvent) and not (
        _is_group_push_subscription_manager(event)
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
        rule=_push_subscription_selection_rule(session_id, version, target_type),
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
        or not _is_group_push_subscription_manager(event)
    ):
        prompt = (
            "普通群成员只能查看本群推送订阅，不能修改；需要群主或管理员操作。\n\n"
            f"{_push_subscription_menu_prompt(target_type, options, read_only=True)}"
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


@push_time_matcher.handle()
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
        return

    selected_index = int(selected)
    if selected_index < 0 or selected_index >= len(options):
        state.pop(PUSH_TIME_SELECTED_KEY, None)
        await _reject_push_time_selection(
            matcher,
            state,
            _push_time_menu_prompt(target_type, options),
        )

    if text == "0":
        await matcher.finish("已退出。")

    option = options[selected_index]
    store = _push_subscription_store()
    normalized: str | None
    try:
        normalized = _normalize_push_time_input(option, text)
    except ValueError as e:
        await _reject_push_time_input(matcher, state, str(e))
        return

    if normalized is None:
        store.clear_time_preference(
            target_type,
            target_id,
            option.key,
            option.preference_type,
        )
        result_message = f"已恢复默认：{option.label}。"
    else:
        store.set_time_preference(
            target_type,
            target_id,
            option.key,
            option.preference_type,
            normalized,
        )
        result_message = f"已设置：{option.label} -> {normalized}。"

    await _refresh_push_time_jobs(option)
    state.pop(PUSH_TIME_SELECTED_KEY, None)
    refreshed_options = _push_time_options(target_type, target_id)
    state[PUSH_TIME_OPTIONS_KEY] = refreshed_options
    prompt = (
        f"{result_message}\n\n"
        f"{_push_time_menu_prompt(target_type, refreshed_options)}"
    )
    await _reject_push_time_selection(matcher, state, prompt)


@group_command_matcher.handle()
async def handle_group_command(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=group_command_matcher,
        state=state,
        action="group_command",
    )


async def register_message_schedules(scheduler: Any) -> None:
    await message_schedules.register_message_schedules(scheduler)


async def refresh_message_schedules() -> None:
    scheduler = _messaging_runtime_state.get("scheduler")
    if scheduler is None:
        return
    await register_message_schedules(scheduler)


def _setup_messaging_runtime(driver: Any, scheduler: Any) -> None:
    if _messaging_runtime_state["registered"]:
        _messaging_runtime_state["scheduler"] = scheduler
        return

    _messaging_runtime_state["scheduler"] = scheduler

    @driver.on_startup
    async def _register_message_schedules_on_startup() -> None:
        await register_message_schedules(scheduler)

    _messaging_runtime_state["registered"] = True


def setup_messaging_runtime() -> None:
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    _setup_messaging_runtime(get_driver(), scheduler)
