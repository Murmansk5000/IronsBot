# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from ironsbot.core.commands import command_text_matches, normalize_command_text
from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.messaging.subscription_options import (
    build_push_subscription_menu,
    build_schedule_subscription_options,
)
from ironsbot.services.messaging.subscriptions import (
    BUILTIN_PUSH_OPTIONS,
    PushSubscriptionOption,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.config.models.messaging import (
        MessageConfig,
        MessageMentionReplyAction,
        MessageReplyAction,
    )
    from ironsbot.core.features import FeatureService
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.messaging.delivery import (
        MessageDelivery,
        MessageLimiter,
    )
    from ironsbot.services.messaging.subscriptions import (
        PushPreferencePruneResult,
        PushPreferenceTarget,
        PushSubscriptionRepository,
        PushTargetType,
        PushTimePreferenceIdentity,
    )
    from ironsbot.services.operations.scheduler import Scheduler

    from .push_time import PushTimeOption


class PushSubscriptionSubmenuProvider(Protocol):
    def subscription_submenu(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str] | None: ...

    def toggle_subscription_option(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
    ) -> str | None: ...


ActionT = TypeVar("ActionT", bound="CommandAction")
KeywordActionT = TypeVar("KeywordActionT", bound="KeywordReplyAction")
logger = logging.getLogger(__name__)

PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS = ("推送管理",)
PUSH_TIME_COMMANDS = ("推送时间", "提醒时间")


@dataclass(frozen=True, slots=True)
class MessagingService:
    _config: MessageConfig
    _activity: ActivityConfig
    _store: PushSubscriptionRepository
    _features: FeatureService
    _delivery: MessageDelivery
    _extra_push_options: tuple[
        Callable[[PushTargetType, int], list[PushSubscriptionOption]],
        ...,
    ] = ()
    _push_message_limiter: MessageLimiter | None = None
    _prepare_extra_push_options: (
        Callable[[PushTargetType, int], Awaitable[str | None]] | None
    ) = None
    _subscription_submenu_providers: tuple[PushSubscriptionSubmenuProvider, ...] = ()

    def match_private_action(
        self,
        text: str,
        user_id: int,
    ) -> MessageReplyAction | None:
        return self._find_action(
            text,
            is_allowed=lambda action: self._features.is_private_feature_allowed(
                user_id,
                action.feature,
            ),
        )

    def match_group_action(
        self,
        text: str,
        *,
        user_id: int,
        group_id: int,
    ) -> MessageReplyAction | None:
        return self._find_action(
            text,
            is_allowed=lambda action: self._features.is_group_feature_allowed(
                user_id,
                group_id,
                action.feature,
            ),
        )

    def match_group_mention_reply(
        self,
        *,
        user_id: int,
        group_id: int,
    ) -> MessageMentionReplyAction | None:
        for action in self._config.mention_replies:
            if (
                action.enabled
                and user_id in self._features.resolve_user_refs(action.user_ids)
                and self._features.is_group_feature_allowed(
                    user_id,
                    group_id,
                    action.feature,
                )
            ):
                return action
        return None

    def _find_action(
        self,
        text: str,
        *,
        is_allowed: Callable[[MessageReplyAction], bool],
    ) -> MessageReplyAction | None:
        command = find_command_action(
            text,
            self._config.commands,
            is_allowed=is_allowed,
        )
        if command is not None:
            return command
        return find_keyword_reply_action(
            text,
            self._config.keyword_replies,
            is_allowed=is_allowed,
        )

    def is_superuser(self, user_id: int) -> bool:
        return self._features.is_superuser(user_id)

    def matches_subscription_command(self, text: str) -> bool:
        return any(
            command_text_matches(text, commands)
            for commands in (
                PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS,
                self._config.push_unsubscribe.commands,
                self._config.push_unsubscribe.restore_commands,
            )
        )

    def matches_push_time_command(self, text: str) -> bool:
        return command_text_matches(text, PUSH_TIME_COMMANDS)

    def subscription_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushSubscriptionOption]:
        extra_options = [
            option
            for provider in self._extra_push_options
            for option in provider(target_type, target_id)
        ]
        return [
            *extra_options,
            *self._builtin_subscription_options(target_type, target_id),
            *self._schedule_subscription_options(target_type, target_id),
        ]

    async def prepare_subscription_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> str | None:
        if self._prepare_extra_push_options is None:
            return None
        return await self._prepare_extra_push_options(target_type, target_id)

    async def prepared_subscription_menu(
        self,
        target_type: PushTargetType,
        target_id: int,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str]:
        preparation_warning = await self.prepare_subscription_options(
            target_type,
            target_id,
        )
        options, prompt = self.subscription_menu(
            target_type,
            target_id,
            read_only=read_only,
        )
        if preparation_warning:
            prompt = f"{preparation_warning}\n\n{prompt}"
        return options, prompt

    def subscription_menu(
        self,
        target_type: PushTargetType,
        target_id: int,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str]:
        options = self.subscription_options(target_type, target_id)
        return options, build_push_subscription_menu(
            title=_push_subscription_menu_title(read_only=read_only),
            options=options,
            read_only=read_only,
        )

    def toggle_subscription(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
    ) -> str:
        for provider in self._subscription_submenu_providers:
            if result := provider.toggle_subscription_option(
                target_type,
                target_id,
                option,
            ):
                return result
        if self._store.is_target_unsubscribed(target_type, target_id, option.key):
            self._store.restore_target(target_type, target_id, option.key)
            return f"已恢复订阅：{option.label}。"
        self._store.unsubscribe_target(
            target_type,
            target_id,
            option.key,
            option.feature,
        )
        return f"已退订：{option.label}。"

    def subscription_submenu(
        self,
        target_type: PushTargetType,
        target_id: int,
        option: PushSubscriptionOption,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str] | None:
        for provider in self._subscription_submenu_providers:
            submenu = provider.subscription_submenu(
                target_type,
                target_id,
                option,
                read_only=read_only,
            )
            if submenu is not None:
                return submenu
        return None

    def push_time_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushTimeOption]:
        from .push_time import build_push_time_options

        return build_push_time_options(
            target_type,
            target_id,
            activity=self._activity,
            config=self._config,
            store=self._store,
            eligible_target_ids=self._eligible_target_ids,
        )

    def update_push_time(
        self,
        *,
        target_type: PushTargetType,
        target_id: int,
        option: PushTimeOption,
        value: str | None,
    ) -> str:
        if value is None:
            self._store.clear_time_preference(
                target_type,
                target_id,
                option.key,
                option.preference_type,
            )
            return f"已恢复默认：{option.label}。"
        self._store.set_time_preference(
            target_type,
            target_id,
            option.key,
            option.preference_type,
            value,
        )
        return f"已设置：{option.label} -> {value}。"

    async def start(self, scheduler: Scheduler) -> None:
        try:
            result = self._prune_stale_preferences()
        except Exception:
            logger.exception("startup push preference cleanup failed")
        else:
            logger.info(
                "startup push preference cleanup complete: "
                "unsubscriptions_deleted=%s, time_preferences_deleted=%s",
                result.unsubscriptions_deleted,
                result.time_preferences_deleted,
            )
        await self.register_schedules(scheduler)

    async def register_schedules(self, scheduler: Scheduler) -> None:
        from .schedules import register_message_schedules

        await register_message_schedules(scheduler, self)

    async def refresh_push_time_jobs(
        self,
        option: PushTimeOption,
        *,
        scheduler: Scheduler,
        activity_service: ActivityService,
    ) -> None:
        from .subscriptions import CRON_TIME_PREFERENCE

        if option.preference_type == CRON_TIME_PREFERENCE:
            await self.register_schedules(scheduler)
            return
        await activity_service.schedule_reminders(scheduler)

    def _eligible_target_ids(
        self,
        target_type: PushTargetType,
        feature_keys: set[str],
    ) -> dict[str, set[int]]:
        if target_type == "group":
            return {
                feature: set(self._features.groups_for_feature(feature))
                for feature in feature_keys
            }
        return {
            feature: set(
                self._features.users_with_superusers(
                    self._features.users_for_feature(feature)
                )
            )
            for feature in feature_keys
        }

    def _builtin_subscription_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushSubscriptionOption]:
        unsubscribed = self._store.target_unsubscribed_keys(target_type, target_id)
        eligible = self._eligible_target_ids(
            target_type,
            {option.feature for option in BUILTIN_PUSH_OPTIONS},
        )
        return [
            PushSubscriptionOption(
                key=option.key,
                label=option.label,
                feature=option.feature,
                unsubscribed=option.key in unsubscribed,
            )
            for option in BUILTIN_PUSH_OPTIONS
            if target_id in eligible.get(option.feature, set())
        ]

    def _schedule_subscription_options(
        self,
        target_type: PushTargetType,
        target_id: int,
    ) -> list[PushSubscriptionOption]:
        tasks = self._config.schedules
        features = {task.feature for task in tasks if task.enabled}
        return build_schedule_subscription_options(
            target_type=target_type,
            target_id=target_id,
            tasks=tasks,
            eligible_target_ids_for_feature=self._eligible_target_ids(
                target_type,
                features,
            ),
            store=self._store,
        )

    def _prune_stale_preferences(self) -> PushPreferencePruneResult:
        valid_unsubscriptions: dict[PushPreferenceTarget, set[str]] = {}
        valid_times: dict[
            PushPreferenceTarget,
            set[PushTimePreferenceIdentity],
        ] = {}
        for target in self._store.preference_targets():
            target_type, target_id = target
            valid_unsubscriptions[target] = {
                option.key
                for option in self.subscription_options(target_type, target_id)
            }
            valid_times[target] = {
                (option.key, option.preference_type)
                for option in self.push_time_options(target_type, target_id)
            }
        return self._store.prune_invalid_preferences(
            valid_unsubscription_keys=valid_unsubscriptions,
            valid_time_preferences=valid_times,
        )


class CommandAction(Protocol):
    enabled: bool
    commands: list[str]


class KeywordReplyAction(Protocol):
    enabled: bool
    keywords: list[str]


class ScheduledAction(Protocol):
    time: str
    day_of_week: str | None


def build_schedule_job_id(prefix: str, index: int, raw_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id or f"task_{index}")
    safe_id = safe_id.strip("_") or str(index)
    return f"{prefix}_{safe_id}"


def build_schedule_trigger_kwargs(task: ScheduledAction) -> dict[str, Any]:
    trigger_kwargs: dict[str, Any] = scheduled_clock_time(
        task.time,
        error_message="messaging.schedules.time must use HH:MM:SS",
    ).cron_kwargs()
    if task.day_of_week:
        trigger_kwargs["day_of_week"] = task.day_of_week
    return trigger_kwargs


def find_command_action(
    text: str,
    actions: Iterable[ActionT],
    *,
    is_allowed: Callable[[ActionT], bool],
) -> ActionT | None:
    for action in actions:
        if not action.enabled or not is_allowed(action):
            continue
        if command_text_matches(text, action.commands):
            return action
    return None


def find_keyword_reply_action(
    text: str,
    actions: Iterable[KeywordActionT],
    *,
    is_allowed: Callable[[KeywordActionT], bool],
) -> KeywordActionT | None:
    normalized_text = normalize_command_text(text)
    if not normalized_text:
        return None
    for action in actions:
        if not action.enabled or not is_allowed(action):
            continue
        if any(
            normalize_command_text(keyword) in normalized_text
            for keyword in action.keywords
        ):
            return action
    return None


def _push_subscription_menu_title(
    *,
    read_only: bool,
) -> str:
    if read_only:
        return "推送订阅状态："
    return "请选择要切换的推送订阅："
