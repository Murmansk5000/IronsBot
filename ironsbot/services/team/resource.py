# SPDX-License-Identifier: MIT
"""Platform-neutral team resource subscriptions and reminder policy."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol

from ironsbot.core.commands import command_text_matches
from ironsbot.core.platform import ActorRef, ConversationRef
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.ids import TEAM_ID_ERROR_MESSAGE, is_valid_team_id
from ironsbot.services.seer.team import format_team_info

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)

TEAM_RESOURCE_FEATURE = "team_resource_subscription"
TEAM_RESOURCE_JOB_PREFIX = "team_resource_scan_"

_ADD_PREFIXES = ("订阅战队", "添加战队", "战队订阅")
_REMOVE_PREFIXES = ("取消订阅战队", "删除订阅战队", "战队取消订阅")
_LIST_COMMANDS = ("战队订阅", "订阅战队", "本群战队")


class TeamResourceResult(NamedTuple):
    team_id: int
    team_name: str
    message: str
    resource: int


class TeamResourceSubscriptionTarget(NamedTuple):
    """A platform recipient that owns a team resource subscription.

    Group subscriptions belong to a ``ConversationRef``. Private subscriptions
    belong to their subscriber ``ActorRef`` because the delivery integration
    determines how that actor receives a direct message.
    """

    recipient: ConversationRef | ActorRef
    mention_actors: tuple[ActorRef, ...] = ()

    @property
    def conversation(self) -> ConversationRef | None:
        return self.recipient if isinstance(self.recipient, ConversationRef) else None

    @property
    def actor(self) -> ActorRef | None:
        return self.recipient if isinstance(self.recipient, ActorRef) else None

    @property
    def is_group(self) -> bool:
        return self.conversation is not None and self.conversation.kind == "group"

    @property
    def is_private(self) -> bool:
        return self.actor is not None


class TeamResourceSubscription(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    threshold: int
    mention_actors: tuple[ActorRef, ...]
    created_by: ActorRef
    updated_by: ActorRef
    created_at: str
    updated_at: str


class TeamResourceSubscriptionUpdate(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    threshold: int
    mention_actors: tuple[ActorRef, ...]
    operator: ActorRef


class TeamResourcePrivateSubscription(NamedTuple):
    actor: ActorRef
    team_id: int
    team_name: str
    threshold: int
    created_at: str
    updated_at: str


class TeamResourcePrivateSubscriptionUpdate(NamedTuple):
    actor: ActorRef
    team_id: int
    team_name: str
    threshold: int


class TeamResourceSubscriptionPrompt(NamedTuple):
    conversation: ConversationRef
    team_id: int
    team_name: str
    prompted_by: ActorRef
    prompted_at: str
    handled_by: ActorRef | None = None
    handled_at: str | None = None
    accepted: bool | None = None

    @property
    def is_pending(self) -> bool:
        return self.handled_at is None


@dataclass(frozen=True, slots=True)
class TeamResourceManageCommand:
    action: Literal["add", "remove", "list"]
    team_id: int | None = None
    threshold: int | None = None
    has_manual_mention: bool = False


class TeamResourceQueryError(RuntimeError):
    @classmethod
    def unavailable(cls, team_id: int) -> TeamResourceQueryError:
        return cls(
            f"战队 {team_id} 暂时查不了："
            "需要连接赛尔号游戏服务器，当前可能在维护、"
            "未开放或无头客户端未登录。"
        )

    @classmethod
    def timeout(cls, team_id: int) -> TeamResourceQueryError:
        return cls(f"战队 {team_id} 查询超时，请稍后再试。")

    @classmethod
    def failed(cls, team_id: int) -> TeamResourceQueryError:
        return cls(f"战队 {team_id} 查询失败，请稍后再试。")


class TeamResourceNoticeSender(Protocol):
    """Deliver a low-resource notice through the target platform."""

    async def send_low_resource_notice(
        self,
        target: TeamResourceSubscriptionTarget,
        message: str,
    ) -> bool: ...


class TeamResourceStore(Protocol):
    def list_all(self) -> list[TeamResourceSubscription]: ...
    def list_conversation(
        self,
        conversation: ConversationRef,
    ) -> list[TeamResourceSubscription]: ...
    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None: ...
    def list_all_private(self) -> list[TeamResourcePrivateSubscription]: ...
    def list_actor(self, actor: ActorRef) -> list[TeamResourcePrivateSubscription]: ...
    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None: ...
    def has_prompted_conversation(self, conversation: ConversationRef) -> bool: ...
    def get_pending_prompt(
        self,
        conversation: ConversationRef,
    ) -> TeamResourceSubscriptionPrompt | None: ...
    def mark_conversation_prompted(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
        prompted_by: ActorRef,
    ) -> None: ...
    def mark_prompt_handled(
        self,
        *,
        conversation: ConversationRef,
        handled_by: ActorRef,
        accepted: bool,
    ) -> None: ...
    def update_team_name(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete(
        self,
        *,
        conversation: ConversationRef,
        team_id: int,
    ) -> bool: ...
    def update_private_team_name(
        self,
        *,
        actor: ActorRef,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete_private(self, *, actor: ActorRef, team_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class TeamResourceService:
    _config: TeamResourceConfig
    _store: TeamResourceStore
    _headless: HeadlessService
    _features: FeatureService
    _sender: TeamResourceNoticeSender
    _default_mention_actors: tuple[ActorRef, ...] = ()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def default_mention_actors(self) -> tuple[ActorRef, ...]:
        return self._default_mention_actors

    def allows_target(
        self,
        actor: ActorRef,
        target: TeamResourceSubscriptionTarget,
    ) -> bool:
        if not self.enabled:
            return False
        if target.conversation is not None:
            return self._features.is_feature_allowed(
                actor,
                target.conversation,
                TEAM_RESOURCE_FEATURE,
            )
        return self._features.is_actor_feature_allowed(actor, TEAM_RESOURCE_FEATURE)

    def is_superuser(self, actor: ActorRef) -> bool:
        return self._features.is_actor_superuser(actor)

    def matches_target_query(
        self,
        text: str,
        *,
        actor: ActorRef,
        target: TeamResourceSubscriptionTarget,
    ) -> bool:
        return self.allows_target(actor, target) and command_text_matches(
            text,
            self._config.commands,
        )

    def parse_manage(self, text: str) -> TeamResourceManageCommand | None:
        return parse_team_resource_manage_command(text)

    def has_pending_prompt(self, conversation: ConversationRef) -> bool:
        return self._store.get_pending_prompt(conversation) is not None

    def offer_subscription(
        self,
        *,
        conversation: ConversationRef,
        actor: ActorRef,
        team_id: int,
        team_name: str,
        can_manage: bool,
    ) -> str | None:
        if (
            not can_manage
            or not self.allows_target(
                actor,
                TeamResourceSubscriptionTarget(conversation),
            )
            or self._store.has_prompted_conversation(conversation)
        ):
            return None

        self._store.mark_conversation_prompted(
            conversation=conversation,
            team_id=team_id,
            team_name=team_name,
            prompted_by=actor,
        )
        label = f"{team_name}（{team_id}）" if team_name else str(team_id)
        return (
            f"本群可以订阅战队 {label} 的资源提醒。\n"
            "是否订阅这个战队？回复“是”或“y”订阅，回复“否”或“n”跳过。\n"
            "本群只提示一次；之后群主/管理员仍可发送"
            "“订阅战队123456”添加更多战队。"
        )

    def subscriptions_message(self, target: TeamResourceSubscriptionTarget) -> str:
        subscriptions = self._subscriptions_for_target(target)
        if not subscriptions:
            return self._empty_subscriptions_message(target)

        lines = ["本群战队订阅：" if target.is_group else "你的战队资源订阅："]
        for index, subscription in enumerate(subscriptions, start=1):
            label = (
                f"{subscription.team_name}（{subscription.team_id}）"
                if subscription.team_name
                else str(subscription.team_id)
            )
            line = f"{index}. {label}｜阈值 {subscription.threshold}"
            if isinstance(subscription, TeamResourceSubscription):
                line += f"｜提醒 {_format_actor_ids(subscription.mention_actors)}"
            lines.append(line)
        lines.extend(("", *self._manage_usage_lines(target)))
        return "\n".join(lines)

    def remove_target_subscription(
        self,
        *,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
    ) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        deleted = self._delete_subscription(target, team_id)
        if deleted:
            prefix = "已取消本群战队订阅" if target.is_group else "已取消战队订阅"
            return f"{prefix}：{team_id}。"
        prefix = "本群没有订阅战队" if target.is_group else "你没有订阅战队"
        return f"{prefix}：{team_id}。"

    async def add_target_subscription(
        self,
        *,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
        threshold: int | None,
        operator: ActorRef,
    ) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        try:
            result = await self.query(team_id)
        except TeamResourceQueryError as error:
            return str(error)

        effective_threshold = threshold or self._config.default_threshold
        mention_actors = (
            tuple(dict.fromkeys(target.mention_actors))
            or self.default_mention_actors
            if target.is_group
            else ()
        )
        self._save_target_subscription(
            target=TeamResourceSubscriptionTarget(target.recipient, mention_actors),
            result=result,
            threshold=effective_threshold,
            operator=operator,
        )
        prefix = "已订阅本群战队" if target.is_group else "已订阅战队"
        reminder = _format_actor_ids(mention_actors) if target.is_group else "你"
        return (
            f"{prefix}：{result.team_name}（{result.team_id}）。\n"
            f"资源阈值：{effective_threshold}\n"
            f"提醒对象：{reminder}"
        )

    def answer_prompt(
        self,
        *,
        conversation: ConversationRef,
        actor: ActorRef,
        accepted: bool,
    ) -> str | None:
        prompt = self._store.get_pending_prompt(conversation)
        if prompt is None:
            return None
        self._store.mark_prompt_handled(
            conversation=conversation,
            handled_by=actor,
            accepted=accepted,
        )
        if not accepted:
            return (
                "已跳过本群战队订阅提示。以后需要时，群主/管理员仍可发送"
                "“订阅战队123456”添加。"
            )

        result = TeamResourceResult(prompt.team_id, prompt.team_name, "", 0)
        target = TeamResourceSubscriptionTarget(
            conversation,
            self.default_mention_actors,
        )
        self._save_target_subscription(
            target=target,
            result=result,
            threshold=self._config.default_threshold,
            operator=actor,
        )
        label = prompt.team_name or str(prompt.team_id)
        return (
            f"已订阅本群战队：{label}（{prompt.team_id}）。\n"
            f"资源阈值：{self._config.default_threshold}\n"
            f"提醒对象：{_format_actor_ids(self.default_mention_actors)}\n"
            "还可以继续发送“订阅战队123456”添加更多战队。"
        )

    async def query_target_messages(
        self,
        target: TeamResourceSubscriptionTarget,
    ) -> list[str]:
        return await self.query_messages(
            (
                subscription.team_id
                for subscription in self._subscriptions_for_target(target)
            ),
        )

    async def query_messages(
        self,
        team_ids: Iterable[int],
    ) -> list[str]:
        return [await self._query_message(team_id) for team_id in team_ids]

    async def query(
        self,
        team_id: int,
    ) -> TeamResourceResult:
        if not is_valid_team_id(team_id):
            raise TeamResourceQueryError(TEAM_ID_ERROR_MESSAGE)
        try:
            return await asyncio.wait_for(
                self._fetch(team_id),
                timeout=self._config.query_timeout_seconds,
            )
        except (NotLoggedInError, DisconnectedError) as error:
            logger.warning("team resource query unavailable for %s: %s", team_id, error)
            raise TeamResourceQueryError.unavailable(team_id) from error
        except TimeoutError as error:
            logger.warning("team resource query timed out for %s", team_id)
            raise TeamResourceQueryError.timeout(team_id) from error
        except Exception as error:
            logger.exception("team resource query failed for %s", team_id)
            raise TeamResourceQueryError.failed(team_id) from error

    async def scan(self) -> None:
        if not self.enabled:
            return
        for target, subscription in self._all_subscriptions():
            if not self._target_has_feature(target):
                continue
            try:
                result = await self.query(subscription.team_id)
            except TeamResourceQueryError:
                continue

            self._update_subscription_name(
                target,
                subscription.team_id,
                result.team_name,
            )
            if result.resource >= subscription.threshold:
                continue
            await self._sender.send_low_resource_notice(
                target,
                self._resource_notice(result, subscription),
            )

    def register_jobs(self, scheduler: Scheduler) -> None:
        if not self.enabled:
            return
        jobs = JobRegistry(scheduler, prefix=TEAM_RESOURCE_JOB_PREFIX)
        for time_text in self._config.times:
            hour_text, minute_text = time_text.split(":", maxsplit=1)
            jobs.add(
                self.scan,
                "cron",
                hour=int(hour_text),
                minute=int(minute_text),
                job_id=time_text.replace(":", ""),
            )

    async def _fetch(
        self,
        team_id: int,
    ) -> TeamResourceResult:
        try:
            game = self._headless.get_game()
            with game.operations.track(
                "战队资源查询",
                f"战队 {team_id}",
                source="战队资源查询",
                background=True,
            ):
                info = await game.get_team_info(team_id)
        except (NotLoggedInError, DisconnectedError) as error:
            await self._headless.mark_unavailable(str(error), source="战队资源查询")
            raise

        await self._headless.mark_available(source="战队资源查询")
        return TeamResourceResult(
            info.team_id,
            info.name,
            format_team_info(info, {"basic", "resource"}),
            info.score,
        )

    async def _query_message(
        self,
        team_id: int,
    ) -> str:
        try:
            return (await self.query(team_id)).message
        except TeamResourceQueryError as error:
            return str(error)

    def _resource_notice(
        self,
        result: TeamResourceResult,
        subscription: TeamResourceSubscription | TeamResourcePrivateSubscription,
    ) -> str:
        line = self._config.resource_line.format(
            team_name=result.team_name,
            team_id=result.team_id,
            resource=result.resource,
            threshold=subscription.threshold,
        )
        return f"{line}\n{self._config.resource_message}"

    def _subscriptions_for_target(
        self,
        target: TeamResourceSubscriptionTarget,
    ) -> Sequence[TeamResourceSubscription | TeamResourcePrivateSubscription]:
        if target.conversation is not None:
            return self._store.list_conversation(target.conversation)
        actor = target.actor
        return [] if actor is None else self._store.list_actor(actor)

    def _all_subscriptions(
        self,
    ) -> Iterable[
        tuple[
            TeamResourceSubscriptionTarget,
            TeamResourceSubscription | TeamResourcePrivateSubscription,
        ]
    ]:
        for subscription in self._store.list_all():
            yield (
                TeamResourceSubscriptionTarget(
                    subscription.conversation,
                    subscription.mention_actors,
                ),
                subscription,
            )
        for subscription in self._store.list_all_private():
            yield (TeamResourceSubscriptionTarget(subscription.actor), subscription)

    def _target_has_feature(self, target: TeamResourceSubscriptionTarget) -> bool:
        if target.conversation is not None:
            return self._features.conversation_has_feature(
                target.conversation,
                TEAM_RESOURCE_FEATURE,
            )
        actor = target.actor
        return actor is not None and self._features.is_actor_feature_allowed(
            actor,
            TEAM_RESOURCE_FEATURE,
        )

    def _update_subscription_name(
        self,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
        team_name: str,
    ) -> None:
        if target.conversation is not None:
            self._store.update_team_name(
                conversation=target.conversation,
                team_id=team_id,
                team_name=team_name,
            )
            return
        actor = target.actor
        if actor is not None:
            self._store.update_private_team_name(
                actor=actor,
                team_id=team_id,
                team_name=team_name,
            )

    def _delete_subscription(
        self,
        target: TeamResourceSubscriptionTarget,
        team_id: int,
    ) -> bool:
        if target.conversation is not None:
            return self._store.delete(
                conversation=target.conversation,
                team_id=team_id,
            )
        actor = target.actor
        return actor is not None and self._store.delete_private(
            actor=actor,
            team_id=team_id,
        )

    def _save_target_subscription(
        self,
        *,
        target: TeamResourceSubscriptionTarget,
        result: TeamResourceResult,
        threshold: int,
        operator: ActorRef,
    ) -> None:
        if target.conversation is not None:
            self._store.upsert(
                TeamResourceSubscriptionUpdate(
                    conversation=target.conversation,
                    team_id=result.team_id,
                    team_name=result.team_name,
                    threshold=threshold,
                    mention_actors=target.mention_actors,
                    operator=operator,
                )
            )
            return
        actor = target.actor
        if actor is not None:
            self._store.upsert_private(
                TeamResourcePrivateSubscriptionUpdate(
                    actor=actor,
                    team_id=result.team_id,
                    team_name=result.team_name,
                    threshold=threshold,
                )
            )

    @staticmethod
    def _empty_subscriptions_message(target: TeamResourceSubscriptionTarget) -> str:
        if target.is_group:
            return (
                "本群还没有订阅战队。\n"
                "群主/管理员可发送：订阅战队123456\n"
                "也可发送：订阅战队123456 1000 @提醒人"
            )
        return (
            "你还没有订阅战队资源。\n"
            "发送：订阅战队123456\n"
            "也可发送：订阅战队123456 1000"
        )

    @staticmethod
    def _manage_usage_lines(
        target: TeamResourceSubscriptionTarget,
    ) -> tuple[str, ...]:
        if target.is_group:
            return (
                "群主/管理员可发送：订阅战队123456 1000 @提醒人",
                "取消订阅：取消订阅战队123456",
            )
        return (
            "发送：订阅战队123456 1000",
            "取消订阅：取消订阅战队123456",
        )


def parse_team_resource_manage_command(
    text: str,
) -> TeamResourceManageCommand | None:
    stripped = re.sub(r"\s+", " ", text.strip())
    manual_mention = re.search(r"@\d{5,}", stripped) is not None
    if stripped in _LIST_COMMANDS:
        return TeamResourceManageCommand("list")

    for action in ("remove", "add"):
        prefixes = _REMOVE_PREFIXES if action == "remove" else _ADD_PREFIXES
        for prefix in prefixes:
            if not stripped.startswith(prefix):
                continue
            rest = stripped[len(prefix) :].strip()
            match = re.match(r"\d+", rest)
            if match is None:
                return TeamResourceManageCommand("list")
            threshold_match = re.search(
                r"(?<!\S)(\d+)(?!\S)",
                rest[match.end() :],
            )
            return TeamResourceManageCommand(
                action,
                int(match.group()),
                (
                    int(threshold_match.group(1))
                    if action == "add" and threshold_match is not None
                    else None
                ),
                manual_mention,
            )
    return None


def _format_actor_ids(actors: tuple[ActorRef, ...]) -> str:
    return "、".join(actor.id for actor in actors) if actors else "无"
