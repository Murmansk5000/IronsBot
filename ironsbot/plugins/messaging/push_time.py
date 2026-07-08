from __future__ import annotations

from dataclasses import dataclass

from ironsbot.shared.config.parsing import positive_int_list
from ironsbot.shared.config.time import normalize_daily_time
from ironsbot.shared.features import (
    groups_for_feature,
    users_for_feature,
    users_with_superusers,
)
from ironsbot.shared.messaging.push_subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
    PushPreferenceType,
    PushTargetType,
    PushUnsubscribeStore,
    group_schedule_key,
    group_schedule_label,
    private_schedule_key,
    private_schedule_label,
)
from ironsbot.shared.selection_menu import (
    DEFAULT_SELECTION_FOOTER,
    SelectionMenuItem,
    format_selection_menu,
)

from .config import get_message_config

DEFAULT_TEXT = "默认"
TIME_INPUT_ERROR = (
    "请输入 HH:MM 格式的时间，例如 22:30；输入“默认”恢复 TOML。"
)
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


def _activity_default_lead_hours_text() -> str:
    from ironsbot.plugins.activity.config import get_activity_config

    return lead_hours_text(get_activity_config().lead_hours)


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


def build_push_time_options(
    target_type: PushTargetType,
    target_id: int,
    *,
    store: PushUnsubscribeStore,
) -> list[PushTimeOption]:
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


def build_push_time_menu_prompt(
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


def push_time_value_prompt(option: PushTimeOption) -> str:
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


def normalize_push_time_input(option: PushTimeOption, text: str) -> str | None:
    value = text.strip()
    if value == DEFAULT_TEXT:
        return None
    if option.preference_type == CRON_TIME_PREFERENCE:
        return normalize_daily_time(value, error_message=TIME_INPUT_ERROR)

    lead_hours = positive_int_list(value)
    if not lead_hours:
        raise ValueError(LEAD_INPUT_ERROR)
    return lead_hours_text(lead_hours)


def daily_time_parts_for_push(value: str) -> tuple[int, int]:
    normalized = normalize_daily_time(value, error_message=TIME_INPUT_ERROR)
    hour_text, minute_text = normalized.split(":", maxsplit=1)
    return int(hour_text), int(minute_text)
