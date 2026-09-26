# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from ironsbot.core.commands import command_text_matches, normalize_command_text
from ironsbot.core.platform import (
    ActorRef,
    ConversationKind,
    ConversationRef,
    private_conversation_for_actor,
)
from ironsbot.core.schedule_rendering import ScheduleRendererRegistry
from ironsbot.core.time import daily_time_parts_with_seconds
from ironsbot.services.messaging.push_time import PUSH_TIME_COMMANDS
from ironsbot.services.messaging.subscription_options import (
    build_push_subscription_menu,
    build_schedule_subscription_options,
    push_subscription_command_texts,
)
from ironsbot.services.messaging.subscriptions import (
    BUILTIN_PUSH_OPTIONS,
    PushSubscriptionOption,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping

    from ironsbot.config.models.activity import ActivityConfig
    from ironsbot.config.models.messaging import (
        MessageConfig,
        MessageMentionReplyAction,
        MessageReplyAction,
    )
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorPrincipal
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.messaging.scheduled_delivery import (
        ScheduledMessageSender,
    )
    from ironsbot.services.messaging.subscriptions import (
        PushPreferencePruneResult,
        PushSubscriptionRepository,
        PushTimePreferenceIdentity,
    )
    from ironsbot.services.messaging.targets import MessageScheduleTargets
    from ironsbot.services.operations.scheduler import Scheduler

    from .push_time import PushTimeOption

ActionT = TypeVar("ActionT", bound="CommandAction")
KeywordActionT = TypeVar("KeywordActionT", bound="KeywordReplyAction")
logger = logging.getLogger(__name__)
ReplyInteraction = Literal["direct", "automatic"]


class PushSubscriptionSubmenuProvider(Protocol):
    """Optional extension point for a nested, configuration-backed push menu."""

    def subscription_submenu(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
        *,
        read_only: bool,
    ) -> tuple[list[PushSubscriptionOption], str] | None: ...

    def toggle_subscription(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class MessagingService:
    _config: MessageConfig
    _activity: ActivityConfig
    _store: PushSubscriptionRepository
    _features: FeatureService
    _schedule_sender: ScheduledMessageSender
    _schedule_targets: MessageScheduleTargets
    _extra_push_options: tuple[
        Callable[[ConversationRef], list[PushSubscriptionOption]],
        ...,
    ] = ()
    _prepare_extra_push_options: (
        Callable[[ConversationRef], Awaitable[str | None]] | None
    ) = None
    _subscription_submenu_providers: tuple[PushSubscriptionSubmenuProvider, ...] = ()
    _mention_reply_targets: tuple[tuple[ActorRef, ...], ...] = ()
    _actor_principal: Callable[[ActorRef], ActorPrincipal] | None = None
    _command_mentions: Mapping[str, tuple[ActorRef, ...]] = field(default_factory=dict)
    schedule_renderers: ScheduleRendererRegistry = field(
        default_factory=ScheduleRendererRegistry
    )

    @property
    def feature_policy(self) -> FeatureService:
        """Expose the policy dependency needed by transport-side role checks."""

        return self._features

    @property
    def portable_command_actions(self) -> tuple[MessageReplyAction, ...]:
        """Return enabled commands for both platform adapters."""

        return tuple(action for action in self._config.commands if action.enabled)

    def command_mentions(self, action_id: str) -> tuple[ActorRef, ...]:
        return self._command_mentions.get(action_id, ())

    @property
    def has_enabled_mention_replies(self) -> bool:
        return any(action.enabled for action in self._config.mention_replies)

    def schedule_mentions(
        self,
        index: int,
    ) -> tuple[ActorRef, ...]:
        """Return precompiled mentions for one configured schedule."""

        return self._schedule_targets.mentions_for(index)

    def match_action(
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
        interaction: ReplyInteraction,
    ) -> MessageReplyAction | None:
        def is_allowed(action: MessageReplyAction) -> bool:
            return self._features.is_feature_allowed(
                actor,
                conversation,
                action.feature,
            )

        command = find_command_action(
            text,
            self._config.commands,
            is_allowed=is_allowed,
        )
        if interaction == "direct":
            return command
        if command is not None:
            return None
        return find_keyword_reply_action(
            text,
            self._config.keyword_replies,
            is_allowed=is_allowed,
        )

    def match_mention_reply(
        self,
        context: MessageInputContext,
    ) -> MessageMentionReplyAction | None:
        """Match a configured actor after command and session routing."""

        message = context.message
        if (
            not context.mentions_bot
            or message.conversation.kind != "group"
            or self._features.is_message_blocked(
                message.actor,
                message.conversation,
            )
        ):
            return None
        if len(self._mention_reply_targets) != len(self._config.mention_replies):
            msg = "mention reply targets do not match configured actions"
            raise RuntimeError(msg)
        principal_for = self._actor_principal
        for action, targets in zip(
            self._config.mention_replies,
            self._mention_reply_targets,
            strict=True,
        ):
            if not action.enabled:
                continue
            if principal_for is None:
                matched = message.actor in targets
            else:
                actor_principal = principal_for(message.actor)
                matched = any(
                    principal_for(target) == actor_principal for target in targets
                )
            if matched:
                return action
        return None

    def matches_subscription_command(self, text: str) -> bool:
        return command_text_matches(
            text,
            push_subscription_command_texts(
                self._config.push_unsubscribe.commands,
                self._config.push_unsubscribe.restore_commands,
            ),
        )

    def matches_push_time_command(self, text: str) -> bool:
        return command_text_matches(text, PUSH_TIME_COMMANDS)

    def subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        extra_options = [
            option
            for provider in self._extra_push_options
            for option in provider(conversation)
        ]
        return [
            *extra_options,
            *self._builtin_subscription_options(conversation),
            *self._schedule_subscription_options(conversation),
        ]

    async def prepare_subscription_options(
        self,
        conversation: ConversationRef,
    ) -> str | None:
        if self._prepare_extra_push_options is None:
            return None
        return await self._prepare_extra_push_options(conversation)

    async def prepared_subscription_menu(
        self,
        conversation: ConversationRef,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str]:
        preparation_warning = await self.prepare_subscription_options(
            conversation,
        )
        options, prompt = self.subscription_menu(
            conversation,
            read_only=read_only,
        )
        if preparation_warning:
            prompt = f"{preparation_warning}\n\n{prompt}"
        return options, prompt

    def subscription_menu(
        self,
        conversation: ConversationRef,
        *,
        read_only: bool = False,
    ) -> tuple[list[PushSubscriptionOption], str]:
        options = self.subscription_options(conversation)
        return options, build_push_subscription_menu(
            title=_push_subscription_menu_title(
                conversation,
                read_only=read_only,
            ),
            options=options,
            read_only=read_only,
        )

    def toggle_subscription(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
    ) -> str:
        for provider in self._subscription_submenu_providers:
            if message := provider.toggle_subscription(conversation, option):
                return message
        if self._store.is_unsubscribed(conversation, option.key):
            self._store.restore(conversation, option.key)
            return f"已恢复订阅：{option.label}。"
        self._store.unsubscribe(
            conversation,
            option.key,
            option.feature,
        )
        return f"已退订：{option.label}。"

    def subscription_submenu(
        self,
        conversation: ConversationRef,
        option: PushSubscriptionOption,
        *,
        read_only: bool,
    ) -> tuple[list[PushSubscriptionOption], str] | None:
        for provider in self._subscription_submenu_providers:
            if submenu := provider.subscription_submenu(
                conversation,
                option,
                read_only=read_only,
            ):
                return submenu
        return None

    def push_time_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushTimeOption]:
        from .push_time import build_push_time_options

        return build_push_time_options(
            conversation,
            activity=self._activity,
            config=self._config,
            store=self._store,
            eligible_conversations=self._eligible_conversations,
        )

    def update_push_time(
        self,
        *,
        conversation: ConversationRef,
        option: PushTimeOption,
        value: str | None,
    ) -> str:
        if value is None:
            self._store.clear_time_preference(
                conversation,
                option.key,
                option.preference_type,
            )
            return f"已恢复默认：{option.label}。"
        self._store.set_time_preference(
            conversation,
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

    def _eligible_conversations(
        self,
        conversation_kind: ConversationKind,
        feature_keys: set[str],
    ) -> dict[str, set[ConversationRef]]:
        if conversation_kind == "group":
            return {
                feature: set(self._features.conversations_for_feature(feature))
                for feature in feature_keys
            }
        if conversation_kind == "private":
            return {
                feature: {
                    private_conversation_for_actor(actor)
                    for actor in self._features.private_actors_for_feature(feature)
                }
                for feature in feature_keys
            }
        return {feature: set() for feature in feature_keys}

    def _builtin_subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        unsubscribed = self._store.unsubscribed_keys(conversation)
        eligible = self._eligible_conversations(
            conversation.kind,
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
            if conversation in eligible.get(option.feature, set())
        ]

    def _schedule_subscription_options(
        self,
        conversation: ConversationRef,
    ) -> list[PushSubscriptionOption]:
        from .schedules import eligible_group_schedule_conversations

        tasks = self._config.schedules
        features = {task.feature for task in tasks if task.enabled}
        options = build_schedule_subscription_options(
            conversation=conversation,
            tasks=tasks,
            eligible_conversations_for_feature=self._eligible_conversations(
                conversation.kind,
                features,
            ),
            store=self._store,
        )
        restricted_keys = {
            task.id
            for index, task in enumerate(tasks, start=1)
            if task.target_groups
            and conversation
            not in eligible_group_schedule_conversations(task, index, messaging=self)
        }
        return [option for option in options if option.key not in restricted_keys]

    def _prune_stale_preferences(self) -> PushPreferencePruneResult:
        valid_unsubscriptions: dict[ConversationRef, set[str]] = {}
        valid_times: dict[
            ConversationRef,
            set[PushTimePreferenceIdentity],
        ] = {}
        for conversation in self._store.preference_conversations():
            valid_unsubscriptions[conversation] = {
                option.key for option in self.subscription_options(conversation)
            }
            valid_times[conversation] = {
                (option.key, option.preference_type)
                for option in self.push_time_options(conversation)
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
    hour, minute, second = daily_time_parts_with_seconds(task.time)
    trigger_kwargs: dict[str, Any] = {
        "hour": hour,
        "minute": minute,
        "second": second,
    }
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
    conversation: ConversationRef,
    *,
    read_only: bool,
) -> str:
    if conversation.kind == "group" and read_only:
        return "本群推送订阅状态："
    scope = "本群" if conversation.kind == "group" else "私聊"
    return f"请选择要切换的{scope}推送订阅："
