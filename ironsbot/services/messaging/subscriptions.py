# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from collections.abc import Set as AbstractSet

    from ironsbot.core.platform import ConversationKind, ConversationRef, Platform

PushPreferenceType = Literal["cron_time", "activity_lead_hours"]
PushTimePreferenceIdentity = tuple[str, PushPreferenceType]
CRON_TIME_PREFERENCE: PushPreferenceType = "cron_time"
ACTIVITY_LEAD_HOURS_PREFERENCE: PushPreferenceType = "activity_lead_hours"


@dataclass(frozen=True, slots=True)
class PushPreferencePruneResult:
    unsubscriptions_deleted: int = 0
    time_preferences_deleted: int = 0

    @property
    def total_deleted(self) -> int:
        return self.unsubscriptions_deleted + self.time_preferences_deleted


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
    def time(self) -> str: ...

    @property
    def day_of_week(self) -> str | None: ...


class PushDeliverySubscriptions(Protocol):
    def filter_subscribed_conversations(
        self,
        conversations: list[ConversationRef],
        subscription_key: str,
    ) -> list[ConversationRef]: ...

    def mark_daily_hint_sent(
        self,
        conversation: ConversationRef,
        hint_key: str,
        *,
        today: str | None = None,
    ) -> bool: ...


class PushSubscriptionRepository(PushDeliverySubscriptions, Protocol):
    def unsubscribed_keys(
        self,
        conversation: ConversationRef,
    ) -> set[str]: ...

    def is_unsubscribed(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> bool: ...

    def unsubscribe(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        feature: str,
    ) -> None: ...

    def restore(
        self,
        conversation: ConversationRef,
        subscription_key: str,
    ) -> None: ...

    def get_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> str | None: ...

    def set_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
        value: str,
    ) -> None: ...

    def clear_time_preference(
        self,
        conversation: ConversationRef,
        subscription_key: str,
        preference_type: PushPreferenceType,
    ) -> None: ...

    def all_time_preferences(
        self,
        *,
        platform: Platform | None = None,
        conversation_kind: ConversationKind | None = None,
        subscription_key: str | None = None,
        preference_type: PushPreferenceType | None = None,
    ) -> list[PushTimePreference]: ...

    def preference_conversations(self) -> set[ConversationRef]: ...

    def prune_invalid_preferences(
        self,
        *,
        valid_unsubscription_keys: Mapping[
            ConversationRef,
            AbstractSet[str],
        ],
        valid_time_preferences: Mapping[
            ConversationRef,
            AbstractSet[PushTimePreferenceIdentity],
        ],
    ) -> PushPreferencePruneResult: ...


@dataclass(frozen=True, slots=True)
class PushSubscriptionOption:
    key: str
    label: str
    feature: str
    unsubscribed: bool = False
    submenu_key: str | None = None


@dataclass(frozen=True, slots=True)
class PushTimePreference:
    conversation: ConversationRef
    subscription_key: str
    preference_type: PushPreferenceType
    value: str
    updated_at: str


BUILTIN_PUSH_OPTIONS: tuple[PushSubscriptionOption, ...] = (
    PushSubscriptionOption("seer_activity_push", "活动结束提醒", "seer_activity_push"),
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
