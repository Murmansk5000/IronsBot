from dataclasses import dataclass
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

from ironsbot.shared.config.parsing import positive_int_list
from ironsbot.shared.config.time import normalize_daily_time
from ironsbot.shared.features import (
    groups_for_feature,
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
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
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    BUILTIN_PUSH_OPTIONS,
    CRON_TIME_PREFERENCE,
    PushPreferenceType,
    PushSubscriptionOption,
    PushTargetType,
    PushUnsubscribeStore,
    build_push_subscription_menu,
    build_schedule_subscription_options,
    group_schedule_key,
    group_schedule_label,
    private_schedule_key,
    private_schedule_label,
)
from ironsbot.shared.messaging.selection_menu import (
    DEFAULT_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
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
PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS = ("推送管理",)
PUSH_TIME_OPTIONS_KEY = "_message_push_time_options"
PUSH_TIME_SELECTED_KEY = "_message_push_time_selected"
PUSH_TIME_SESSION_KEY = "_message_push_time_session"
PUSH_TIME_TARGET_ID_KEY = "_message_push_time_target_id"
PUSH_TIME_TARGET_TYPE_KEY = "_message_push_time_target_type"
PUSH_TIME_VERSION_KEY = "_message_push_time_version"
PUSH_TIME_NAMESPACE = "message_push_time"
PUSH_TIME_COMMANDS = ("推送时间", "提醒时间")
MESSAGE_PLUGIN_NAME = "message"
MESSAGE_SCHEDULE_JOB_PREFIX = "message_action_"
DEFAULT_TEXT = "默认"
TIME_INPUT_ERROR = "请输入 HH:MM 格式的时间，例如 22:30；输入“默认”恢复 TOML。"
LEAD_INPUT_ERROR = "请输入正整数小时列表，例如 24,3,1；输入“默认”恢复 TOML。"
_messaging_runtime_state = {"registered": False, "scheduler": None}


@dataclass(frozen=True, slots=True)
class PushTimeOption:
    key: str
    label: str
    feature: str
    preference_type: PushPreferenceType
    default_value: str
    current_value: str
    overridden: bool = False


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


def _push_subscription_menu_title(
    target_type: PushTargetType,
    *,
    read_only: bool = False,
) -> str:
    if target_type == "group" and read_only:
        return "本群推送订阅状态："
    scope = "本群" if target_type == "group" else "私聊"
    return f"请选择要切换的{scope}推送订阅："


def _push_subscription_menu_prompt(
    target_type: PushTargetType,
    options: list[PushSubscriptionOption],
    *,
    read_only: bool = False,
) -> str:
    return build_push_subscription_menu(
        title=_push_subscription_menu_title(target_type, read_only=read_only),
        options=options,
        read_only=read_only,
    )


def _schedule_time_option_label(
    *,
    base_label: str,
    default_value: str,
    current_value: str,
    overridden: bool,
) -> str:
    source = "覆盖" if overridden else "默认"
    return f"{base_label}：{current_value}（{source}，默认 {default_value}）"


def _lead_hours_text(values: list[int]) -> str:
    return ",".join(str(value) for value in values)


def _activity_default_lead_hours_text() -> str:
    from ironsbot.plugins.activity.config import get_activity_config

    return _lead_hours_text(get_activity_config().lead_hours)


def _activity_time_option(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> PushTimeOption | None:
    eligible = _eligible_target_ids_by_feature(target_type, {"seer_activity_push"})
    if target_id not in eligible.get("seer_activity_push", set()):
        return None

    key = "seer_activity_push"
    default_value = _activity_default_lead_hours_text()
    override = store.get_time_preference(
        target_type,
        target_id,
        key,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
    )
    current_value = override or default_value
    return PushTimeOption(
        key=key,
        label=(
            "活动结束提醒："
            f"提前 {current_value} 小时"
            f"（{'覆盖' if override else '默认'}，默认 {default_value}）"
        ),
        feature="seer_activity_push",
        preference_type=ACTIVITY_LEAD_HOURS_PREFERENCE,
        default_value=default_value,
        current_value=current_value,
        overridden=override is not None,
    )


def _schedule_time_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
) -> list[PushTimeOption]:
    config = get_message_config()
    tasks = (
        config.group_schedules
        if target_type == "group"
        else config.private_schedules
    )
    features = {task.feature for task in tasks if task.enabled}
    eligible = _eligible_target_ids_by_feature(target_type, features)

    options: list[PushTimeOption] = []
    for index, task in enumerate(tasks, start=1):
        if not task.enabled:
            continue
        if target_id not in eligible.get(task.feature, set()):
            continue

        key = (
            group_schedule_key(index, task)
            if target_type == "group"
            else private_schedule_key(index, task)
        )
        default_value = f"{task.hour:02d}:{task.minute:02d}"
        override = store.get_time_preference(
            target_type,
            target_id,
            key,
            CRON_TIME_PREFERENCE,
        )
        current_value = override or default_value
        base_label = (
            group_schedule_label(index, task)
            if target_type == "group"
            else private_schedule_label(index, task)
        )
        options.append(
            PushTimeOption(
                key=key,
                label=_schedule_time_option_label(
                    base_label=base_label,
                    default_value=default_value,
                    current_value=current_value,
                    overridden=override is not None,
                ),
                feature=task.feature,
                preference_type=CRON_TIME_PREFERENCE,
                default_value=default_value,
                current_value=current_value,
                overridden=override is not None,
            )
        )
    return options


def _push_time_options(
    target_type: PushTargetType,
    target_id: int,
) -> list[PushTimeOption]:
    store = _push_subscription_store()
    options: list[PushTimeOption] = []
    activity_option = _activity_time_option(
        target_type=target_type,
        target_id=target_id,
        store=store,
    )
    if activity_option is not None:
        options.append(activity_option)
    options.extend(
        _schedule_time_options(
            target_type=target_type,
            target_id=target_id,
            store=store,
        )
    )
    return options


def _push_time_menu_title(target_type: PushTargetType) -> str:
    scope = "本群" if target_type == "group" else "私聊"
    return f"请选择要修改时间的{scope}推送："


def _push_time_menu_prompt(
    target_type: PushTargetType,
    options: list[PushTimeOption],
) -> str:
    return format_selection_menu(
        title=_push_time_menu_title(target_type),
        items=tuple(
            SelectionMenuItem(
                label=option.label,
                prefix="🕒",
            )
            for option in options
        ),
        footer=DEFAULT_SELECTION_FOOTER,
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


def _push_time_selection_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: MessageEvent) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if (
            event_conversation_session_id(PUSH_TIME_NAMESPACE, next_event)
            != session_id
        ):
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return next_event.get_plaintext().strip().isdigit()

    return prompt_session_manager.make_rule(session_id, version, _check)


def _push_time_input_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: MessageEvent) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if (
            event_conversation_session_id(PUSH_TIME_NAMESPACE, next_event)
            != session_id
        ):
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return bool(next_event.get_plaintext().strip())

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


async def _reject_push_time_selection(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_TIME_SESSION_KEY)
    version = state.get(PUSH_TIME_VERSION_KEY)
    target_type = state.get(PUSH_TIME_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_time_selection_rule(session_id, version, target_type),
        prompt=prompt,
    )


async def _reject_push_time_input(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_TIME_SESSION_KEY)
    version = state.get(PUSH_TIME_VERSION_KEY)
    target_type = state.get(PUSH_TIME_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_time_input_rule(session_id, version, target_type),
        prompt=prompt,
    )


def _push_time_value_prompt(option: PushTimeOption) -> str:
    if option.preference_type == CRON_TIME_PREFERENCE:
        return (
            f"请输入“{option.label}”的新时间，格式 HH:MM。\n"
            f"当前：{option.current_value}；默认：{option.default_value}。\n"
            "发送“默认”恢复 TOML，输入 0 退出。"
        )
    return (
        f"请输入“{option.label}”的提前小时列表，例如 24,3,1。\n"
        f"当前：{option.current_value}；默认：{option.default_value}。\n"
        "发送“默认”恢复 TOML，输入 0 退出。"
    )


def _normalize_push_time_input(option: PushTimeOption, text: str) -> str | None:
    value = text.strip()
    if value == DEFAULT_TEXT:
        return None
    if option.preference_type == CRON_TIME_PREFERENCE:
        return normalize_daily_time(value, error_message=TIME_INPUT_ERROR)

    lead_hours = positive_int_list(value)
    if not lead_hours:
        raise ValueError(LEAD_INPUT_ERROR)
    return _lead_hours_text(lead_hours)


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

    if target_type == "group" and not _is_group_push_subscription_manager(event):
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
    try:
        normalized = _normalize_push_time_input(option, text)
    except ValueError as e:
        await _reject_push_time_input(matcher, state, str(e))

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


async def _send_private_schedule(
    task: PrivateScheduledMessageAction,
    index: int = 1,
    target_user_ids: tuple[int, ...] | None = None,
) -> None:
    private_user_ids = users_with_superusers(users_for_feature(task.feature))
    if target_user_ids is None:
        override_user_ids = _cron_override_target_ids(
            "private",
            private_schedule_key(index, task),
        )
        private_user_ids = [
            user_id for user_id in private_user_ids if user_id not in override_user_ids
        ]
    else:
        allowed_user_ids = set(private_user_ids)
        private_user_ids = [
            user_id for user_id in target_user_ids if user_id in allowed_user_ids
        ]

    await send_broadcast_message(
        append_fire_manual_ad_text(task.message),
        private_user_ids=private_user_ids,
        action_name=f"private scheduled message {task.id or '<unnamed>'}",
        subscription_key=private_schedule_key(index, task),
    )


async def _send_group_schedule(
    task: GroupScheduledMessageAction,
    index: int = 1,
    target_group_ids: tuple[int, ...] | None = None,
) -> None:
    group_ids = groups_for_feature(task.feature)
    if target_group_ids is None:
        override_group_ids = _cron_override_target_ids(
            "group",
            group_schedule_key(index, task),
        )
        group_ids = [
            group_id for group_id in group_ids if group_id not in override_group_ids
        ]
    else:
        allowed_group_ids = set(group_ids)
        group_ids = [
            group_id for group_id in target_group_ids if group_id in allowed_group_ids
        ]

    await send_broadcast_message(
        task.message,
        group_ids=group_ids,
        group_at_user_ids=task.at_user_ids,
        action_name=f"group scheduled message {task.id or '<unnamed>'}",
        message_limiter=append_fire_manual_ad_for_group,
        subscription_key=group_schedule_key(index, task),
    )


def _cron_override_target_ids(
    target_type: PushTargetType,
    subscription_key: str,
) -> set[int]:
    store = _push_subscription_store()
    return {
        preference.target_id
        for preference in store.all_time_preferences(
            target_type=target_type,
            subscription_key=subscription_key,
            preference_type=CRON_TIME_PREFERENCE,
        )
    }


def _schedule_override_job_id(
    prefix: str,
    index: int,
    task_id: str,
    target_id: int,
) -> str:
    return build_schedule_job_id(prefix, index, f"{task_id}_override_{target_id}")


def _schedule_override_trigger_kwargs(
    task: PrivateScheduledMessageAction | GroupScheduledMessageAction,
    value: str,
) -> dict[str, int | str]:
    hour, minute = daily_time_parts_for_push(value)
    trigger_kwargs = build_schedule_trigger_kwargs(task)
    trigger_kwargs["hour"] = hour
    trigger_kwargs["minute"] = minute
    return trigger_kwargs


def daily_time_parts_for_push(value: str) -> tuple[int, int]:
    normalized = normalize_daily_time(value, error_message=TIME_INPUT_ERROR)
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return int(hour_text), int(minute_text)


def _register_private_schedule_overrides(
    scheduler: Any,
    index: int,
    task: PrivateScheduledMessageAction,
) -> None:
    key = private_schedule_key(index, task)
    eligible_user_ids = set(users_with_superusers(users_for_feature(task.feature)))
    store = _push_subscription_store()
    for preference in store.all_time_preferences(
        target_type="private",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.target_id not in eligible_user_ids:
            continue
        try:
            trigger_kwargs = _schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        scheduler.add_job(
            _send_private_schedule,
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_user_ids": (preference.target_id,),
            },
            id=_schedule_override_job_id(
                "private_schedule",
                index,
                key,
                preference.target_id,
            ),
            replace_existing=True,
            **trigger_kwargs,
        )


def _register_group_schedule_overrides(
    scheduler: Any,
    index: int,
    task: GroupScheduledMessageAction,
) -> None:
    key = group_schedule_key(index, task)
    eligible_group_ids = set(groups_for_feature(task.feature))
    store = _push_subscription_store()
    for preference in store.all_time_preferences(
        target_type="group",
        subscription_key=key,
        preference_type=CRON_TIME_PREFERENCE,
    ):
        if preference.target_id not in eligible_group_ids:
            continue
        try:
            trigger_kwargs = _schedule_override_trigger_kwargs(task, preference.value)
        except ValueError:
            continue
        scheduler.add_job(
            _send_group_schedule,
            "cron",
            kwargs={
                "task": task,
                "index": index,
                "target_group_ids": (preference.target_id,),
            },
            id=_schedule_override_job_id(
                "group_schedule",
                index,
                key,
                preference.target_id,
            ),
            replace_existing=True,
            **trigger_kwargs,
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
    _register_private_schedule_overrides(scheduler, index, task)


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
    _register_group_schedule_overrides(scheduler, index, task)


async def register_message_schedules(scheduler: Any) -> None:
    _clear_message_schedule_jobs(scheduler)
    config = get_message_config()
    for index, task in enumerate(config.private_schedules, start=1):
        _register_private_schedule(scheduler, index, task)

    for index, task in enumerate(config.group_schedules, start=1):
        _register_group_schedule(scheduler, index, task)


def _clear_message_schedule_jobs(scheduler: Any) -> None:
    get_jobs = getattr(scheduler, "get_jobs", None)
    remove_job = getattr(scheduler, "remove_job", None)
    if not callable(get_jobs) or not callable(remove_job):
        return

    for job in list(get_jobs()):
        job_id = str(getattr(job, "id", ""))
        if job_id.startswith(MESSAGE_SCHEDULE_JOB_PREFIX):
            remove_job(job_id)


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
