# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

PushTargetType = Literal["private", "group"]
PushPreferenceType = Literal["cron_time", "activity_lead_hours"]
CRON_TIME_PREFERENCE: PushPreferenceType = "cron_time"
ACTIVITY_LEAD_HOURS_PREFERENCE: PushPreferenceType = "activity_lead_hours"


class ScheduledPushTask(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def feature(self) -> str: ...

    @property
    def message(self) -> str: ...

    @property
    def hour(self) -> int: ...

    @property
    def minute(self) -> int: ...

    @property
    def day_of_week(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class PushSubscriptionOption:
    key: str
    label: str
    feature: str
    unsubscribed: bool = False


@dataclass(frozen=True, slots=True)
class PushTimePreference:
    target_type: PushTargetType
    target_id: int
    subscription_key: str
    preference_type: PushPreferenceType
    value: str
    updated_at: str


BUILTIN_PUSH_OPTIONS: tuple[PushSubscriptionOption, ...] = (
    PushSubscriptionOption("seer_activity_push", "活动结束提醒", "seer_activity_push"),
    PushSubscriptionOption("server_status_push", "开服推送", "server_status_push"),
    PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
    PushSubscriptionOption("startup_docker_update", "启动镜像检查通知", "admin_notice"),
    PushSubscriptionOption("startup_data_sync", "启动数据同步通知", "admin_notice"),
    PushSubscriptionOption("ai_chat_error_notice", "AI聊天异常通知", "admin_notice"),
    PushSubscriptionOption("bili_login_notice", "B站登录通知", "admin_notice"),
    PushSubscriptionOption("headless_seer_notice", "无头赛尔号通知", "admin_notice"),
    PushSubscriptionOption("render_crash_notice", "精灵渲染崩溃通知", "admin_notice"),
    PushSubscriptionOption("red_packet_notice", "红包提醒", "admin_notice"),
    PushSubscriptionOption("admin_notice", "其他管理通知", "admin_notice"),
)


__all__ = [
    "ACTIVITY_LEAD_HOURS_PREFERENCE",
    "BUILTIN_PUSH_OPTIONS",
    "CRON_TIME_PREFERENCE",
    "PushPreferenceType",
    "PushSubscriptionOption",
    "PushTargetType",
    "PushTimePreference",
    "ScheduledPushTask",
]
