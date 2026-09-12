# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.commands import positive_int_list
from ironsbot.core.platform import ConversationKind, ConversationRef
from ironsbot.core.selection import (
    DEFAULT_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
)
from ironsbot.core.time import (
    daily_time_parts_with_seconds,
    normalize_daily_time_with_seconds,
)
from ironsbot.services.messaging.subscription_options import (
    schedule_key,
    schedule_label,
)
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
    PushPreferenceType,
)

if TYPE_CHECKING:
    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.config.models.messaging import MessageConfig
    from ironsbot.services.messaging.subscriptions import (
        PushSubscriptionRepository,
    )

EligibleConversations = Callable[
    [ConversationKind, set[str]],
    dict[str, set[ConversationRef]],
]

DEFAULT_TEXT = "默认"
PUSH_TIME_COMMANDS = ("推送时间", "提醒时间")
TIME_INPUT_ERROR = "请输入 HH:MM 或 HH:MM:SS 时间，例如 22:30；输入“默认”恢复 TOML。"
LEAD_INPUT_ERROR = "请输入正整数小时列表，例如 24,3,1；输入“默认”恢复 TOML。"


@dataclass(frozen=True, slots=True)
class PushTimeOption:
    key: str
    label: str
    feature: str
    preference_type: PushPreferenceType
    default_value: str
    current_value: str
    overridden: bool = False


def _schedule_time_option_label(
    *,
    base_label: str,
    default_value: str,
    current_value: str,
    overridden: bool,
) -> str:
    source = "覆盖" if overridden else "默认"
    return f"{base_label}：{current_value}（{source}，默认 {default_value}）"


def lead_hours_text(values: list[int]) -> str:
    return ",".join(str(value) for value in values)


def _activity_time_option(
    *,
    conversation: ConversationRef,
    config: ActivityConfig,
    store: PushSubscriptionRepository,
    eligible_conversations: EligibleConversations,
) -> PushTimeOption | None:
    eligible = eligible_conversations(conversation.kind, {"seer_activity_push"})
    if conversation not in eligible.get("seer_activity_push", set()):
        return None

    key = "seer_activity_push"
    default_value = lead_hours_text(config.lead_hours)
    override = store.get_time_preference(
        conversation,
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
    conversation: ConversationRef,
    config: MessageConfig,
    store: PushSubscriptionRepository,
    eligible_conversations: EligibleConversations,
) -> list[PushTimeOption]:
    tasks = config.schedules
    features = {task.feature for task in tasks if task.enabled}
    eligible = eligible_conversations(conversation.kind, features)

    options: list[PushTimeOption] = []
    for index, task in enumerate(tasks, start=1):
        if not task.enabled:
            continue
        if conversation not in eligible.get(task.feature, set()):
            continue

        key = schedule_key(index, task)
        default_value = task.time
        override = store.get_time_preference(
            conversation,
            key,
            CRON_TIME_PREFERENCE,
        )
        current_value = override or default_value
        base_label = schedule_label(index, task)
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


def build_push_time_options(
    conversation: ConversationRef,
    *,
    activity: ActivityConfig,
    config: MessageConfig,
    store: PushSubscriptionRepository,
    eligible_conversations: EligibleConversations,
) -> list[PushTimeOption]:
    options: list[PushTimeOption] = []
    activity_option = _activity_time_option(
        conversation=conversation,
        config=activity,
        store=store,
        eligible_conversations=eligible_conversations,
    )
    if activity_option is not None:
        options.append(activity_option)
    options.extend(
        _schedule_time_options(
            conversation=conversation,
            config=config,
            store=store,
            eligible_conversations=eligible_conversations,
        )
    )
    return options


def _push_time_menu_title(conversation: ConversationRef) -> str:
    scope = "本群" if conversation.kind == "group" else "私聊"
    return f"请选择要修改时间的{scope}推送："


def build_push_time_menu_prompt(
    conversation: ConversationRef,
    options: list[PushTimeOption],
) -> str:
    return format_selection_menu(
        title=_push_time_menu_title(conversation),
        items=tuple(
            SelectionMenuItem(
                label=option.label,
                prefix="🕒",
            )
            for option in options
        ),
        footer=DEFAULT_SELECTION_FOOTER,
    )


def push_time_value_prompt(option: PushTimeOption) -> str:
    if option.preference_type == CRON_TIME_PREFERENCE:
        return (
            f"请输入“{option.label}”的新时间，格式 HH:MM 或 HH:MM:SS。\n"
            f"当前：{option.current_value}；默认：{option.default_value}。\n"
            "发送“默认”恢复 TOML，输入 0 退出。"
        )
    return (
        f"请输入“{option.label}”的提前小时列表，例如 24,3,1。\n"
        f"当前：{option.current_value}；默认：{option.default_value}。\n"
        "发送“默认”恢复 TOML，输入 0 退出。"
    )


def normalize_push_time_input(option: PushTimeOption, text: str) -> str | None:
    value = text.strip()
    if value == DEFAULT_TEXT:
        return None
    if option.preference_type == CRON_TIME_PREFERENCE:
        return normalize_daily_time_with_seconds(value, error_message=TIME_INPUT_ERROR)

    lead_hours = positive_int_list(value)
    if not lead_hours:
        raise ValueError(LEAD_INPUT_ERROR)
    return lead_hours_text(lead_hours)


def daily_time_parts_for_push(value: str) -> tuple[int, int, int]:
    return daily_time_parts_with_seconds(value, error_message=TIME_INPUT_ERROR)
