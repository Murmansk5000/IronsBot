# SPDX-License-Identifier: MIT
"""Platform-neutral team resource subscriptions and reminder policy."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol

from ironsbot.core.commands import command_text_matches
from ironsbot.core.time import scheduled_clock_time
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.ids import TEAM_ID_ERROR_MESSAGE, is_valid_team_id
from ironsbot.services.seer.team import format_team_info
from ironsbot.services.team.resource_subscriptions import (
    TeamResourceManageCommand,
    TeamResourcePrivateSubscription,
    TeamResourcePrivateSubscriptionUpdate,
    TeamResourceStore,
    TeamResourceSubscription,
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
    format_subscription_actors,
    parse_team_resource_manage_command,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.scheduler import Scheduler

logger = logging.getLogger(__name__)

TEAM_RESOURCE_FEATURE = "team_resource_subscription"
TEAM_RESOURCE_JOB_PREFIX = "team_resource_scan_"

class TeamResourceResult(NamedTuple):
    team_id: int
    team_name: str
    message: str
    resource: int


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
    def query_commands(self) -> tuple[str, ...]:
        return tuple(self._config.commands)

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
            self.query_commands,
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
                line += (
                    "｜提醒 "
                    f"{format_subscription_actors(subscription.mention_actors)}"
                )
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
            or self._default_mentions_for(target)
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
        reminder = (
            format_subscription_actors(mention_actors)
            if target.is_group
            else "你"
        )
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
            self._default_mentions_for(TeamResourceSubscriptionTarget(conversation)),
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
            "提醒对象："
            f"{format_subscription_actors(self.default_mention_actors)}\n"
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
            clock_time = scheduled_clock_time(
                time_text,
                error_message="invalid team resource scan time",
            )
            jobs.add_daily(
                self.scan,
                clock_time=clock_time,
                job_id=str(clock_time).replace(":", ""),
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

    def _default_mentions_for(
        self,
        target: TeamResourceSubscriptionTarget,
    ) -> tuple[ActorRef, ...]:
        conversation = target.conversation
        if conversation is None:
            return ()
        return tuple(
            actor
            for actor in self.default_mention_actors
            if actor.platform is conversation.platform
        )

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
