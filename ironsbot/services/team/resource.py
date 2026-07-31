# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol

from ironsbot.core.commands import command_text_matches
from ironsbot.core.messaging import MessageTarget
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.operations.scheduler import JobRegistry
from ironsbot.services.seer.ids import (
    TEAM_ID_ERROR_MESSAGE,
    is_valid_team_id,
)
from ironsbot.services.seer.team import format_team_info

if TYPE_CHECKING:
    from collections.abc import Iterable
    from typing import Literal

    from ironsbot.config.models.seer import TeamResourceConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.core.onebot_references import OneBotReferenceResolver
    from ironsbot.services.messaging.delivery import MessageDelivery
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


class TeamResourceSubscription(NamedTuple):
    group_id: int
    team_id: int
    team_name: str
    threshold: int
    at_user_ids: tuple[int, ...]
    created_by: int
    updated_by: int
    created_at: str
    updated_at: str


class TeamResourceSubscriptionUpdate(NamedTuple):
    group_id: int
    team_id: int
    team_name: str
    threshold: int
    at_user_ids: tuple[int, ...]
    operator_id: int


class TeamResourcePrivateSubscription(NamedTuple):
    user_id: int
    team_id: int
    team_name: str
    threshold: int
    created_at: str
    updated_at: str


class TeamResourcePrivateSubscriptionUpdate(NamedTuple):
    user_id: int
    team_id: int
    team_name: str
    threshold: int


class TeamResourceSubscriptionPrompt(NamedTuple):
    group_id: int
    team_id: int
    team_name: str
    prompted_by: int
    prompted_at: str
    handled_by: int | None = None
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


class TeamResourceStore(Protocol):
    def list_all(self) -> list[TeamResourceSubscription]: ...
    def list_group(self, group_id: int) -> list[TeamResourceSubscription]: ...
    def upsert(self, update: TeamResourceSubscriptionUpdate) -> None: ...
    def list_all_private(self) -> list[TeamResourcePrivateSubscription]: ...
    def list_user(self, user_id: int) -> list[TeamResourcePrivateSubscription]: ...
    def upsert_private(self, update: TeamResourcePrivateSubscriptionUpdate) -> None: ...
    def has_prompted_group(self, group_id: int) -> bool: ...
    def get_pending_prompt(
        self,
        group_id: int,
    ) -> TeamResourceSubscriptionPrompt | None: ...
    def mark_group_prompted(
        self,
        *,
        group_id: int,
        team_id: int,
        team_name: str,
        prompted_by: int,
    ) -> None: ...
    def mark_prompt_handled(
        self,
        *,
        group_id: int,
        handled_by: int,
        accepted: bool,
    ) -> None: ...
    def update_team_name(
        self,
        *,
        group_id: int,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete(self, *, group_id: int, team_id: int) -> bool: ...
    def update_private_team_name(
        self,
        *,
        user_id: int,
        team_id: int,
        team_name: str,
    ) -> None: ...
    def delete_private(self, *, user_id: int, team_id: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class TeamResourceService:
    _config: TeamResourceConfig
    _store: TeamResourceStore
    _headless: HeadlessService
    _references: OneBotReferenceResolver
    _features: FeatureService
    _delivery: MessageDelivery

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def default_at_user_ids(self) -> tuple[int, ...]:
        return tuple(
            self._references.resolve_users(
                self._config.default_at_users,
                location="seer.team_resource.default_at_users",
            )
        )

    def allows(self, user_id: int, group_id: int) -> bool:
        return self.enabled and self._features.is_group_feature_allowed(
            user_id,
            group_id,
            TEAM_RESOURCE_FEATURE,
        )

    def allows_private(self, user_id: int) -> bool:
        return self.enabled and self._features.is_private_feature_allowed(
            user_id,
            TEAM_RESOURCE_FEATURE,
        )

    def is_superuser(self, user_id: int) -> bool:
        return self._features.is_superuser(user_id)

    def matches_query(self, text: str, *, user_id: int, group_id: int) -> bool:
        return self.allows(user_id, group_id) and command_text_matches(
            text,
            self._config.commands,
        )

    def matches_private_query(self, text: str, *, user_id: int) -> bool:
        return self.allows_private(user_id) and command_text_matches(
            text,
            self._config.commands,
        )

    def parse_manage(self, text: str) -> TeamResourceManageCommand | None:
        return parse_team_resource_manage_command(text)

    def has_pending_prompt(self, group_id: int) -> bool:
        return self._store.get_pending_prompt(group_id) is not None

    def offer_subscription(
        self,
        *,
        group_id: int,
        user_id: int,
        team_id: int,
        team_name: str,
        can_manage: bool,
    ) -> str | None:
        if (
            not can_manage
            or not self.allows(user_id, group_id)
            or self._store.has_prompted_group(group_id)
        ):
            return None

        self._store.mark_group_prompted(
            group_id=group_id,
            team_id=team_id,
            team_name=team_name,
            prompted_by=user_id,
        )
        label = f"{team_name}（{team_id}）" if team_name else str(team_id)
        return (
            f"本群可以订阅战队 {label} 的资源提醒。\n"
            "是否订阅这个战队？回复“是”或“y”订阅，回复“否”或“n”跳过。\n"
            "本群只提示一次；之后群主/管理员仍可发送"
            "“订阅战队123456”添加更多战队。"
        )

    def group_subscriptions_message(self, group_id: int) -> str:
        subscriptions = self._store.list_group(group_id)
        if not subscriptions:
            return (
                "本群还没有订阅战队。\n"
                "群主/管理员可发送：订阅战队123456\n"
                "也可发送：订阅战队123456 1000 @提醒人"
            )

        lines = ["本群战队订阅："]
        for index, subscription in enumerate(subscriptions, start=1):
            label = (
                f"{subscription.team_name}（{subscription.team_id}）"
                if subscription.team_name
                else str(subscription.team_id)
            )
            lines.append(
                f"{index}. {label}｜阈值 {subscription.threshold}"
                f"｜提醒 {_format_user_ids(subscription.at_user_ids)}"
            )
        lines.extend(
            (
                "",
                "群主/管理员可发送：订阅战队123456 1000 @提醒人",
                "取消订阅：取消订阅战队123456",
            )
        )
        return "\n".join(lines)

    def private_subscriptions_message(self, user_id: int) -> str:
        subscriptions = self._store.list_user(user_id)
        if not subscriptions:
            return (
                "你还没有订阅战队资源。\n"
                "发送：订阅战队123456\n"
                "也可发送：订阅战队123456 1000"
            )

        lines = ["你的战队资源订阅："]
        for index, subscription in enumerate(subscriptions, start=1):
            label = (
                f"{subscription.team_name}（{subscription.team_id}）"
                if subscription.team_name
                else str(subscription.team_id)
            )
            lines.append(f"{index}. {label}｜阈值 {subscription.threshold}")
        lines.extend(
            (
                "",
                "发送：订阅战队123456 1000",
                "取消订阅：取消订阅战队123456",
            )
        )
        return "\n".join(lines)

    def remove_subscription(self, *, group_id: int, team_id: int) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        deleted = self._store.delete(group_id=group_id, team_id=team_id)
        return (
            f"已取消本群战队订阅：{team_id}。"
            if deleted
            else f"本群没有订阅战队：{team_id}。"
        )

    async def add_subscription(
        self,
        *,
        group_id: int,
        team_id: int,
        threshold: int | None,
        at_user_ids: Iterable[int],
        operator_id: int,
    ) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        try:
            result = await self.query(team_id, group_id=group_id)
        except TeamResourceQueryError as error:
            return str(error)

        effective_threshold = threshold or self._config.default_threshold
        effective_users = tuple(dict.fromkeys(at_user_ids)) or self.default_at_user_ids
        self._save_subscription(
            group_id=group_id,
            result=result,
            threshold=effective_threshold,
            at_user_ids=effective_users,
            operator_id=operator_id,
        )
        return (
            f"已订阅本群战队：{result.team_name}（{result.team_id}）。\n"
            f"资源阈值：{effective_threshold}\n"
            f"提醒对象：{_format_user_ids(effective_users)}"
        )

    async def add_private_subscription(
        self,
        *,
        user_id: int,
        team_id: int,
        threshold: int | None,
    ) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        try:
            result = await self.query(team_id)
        except TeamResourceQueryError as error:
            return str(error)

        effective_threshold = threshold or self._config.default_threshold
        self._store.upsert_private(
            TeamResourcePrivateSubscriptionUpdate(
                user_id=user_id,
                team_id=result.team_id,
                team_name=result.team_name,
                threshold=effective_threshold,
            )
        )
        return (
            f"已订阅战队：{result.team_name}（{result.team_id}）。\n"
            f"资源阈值：{effective_threshold}\n"
            "提醒对象：你"
        )

    def remove_private_subscription(self, *, user_id: int, team_id: int) -> str:
        if not is_valid_team_id(team_id):
            return TEAM_ID_ERROR_MESSAGE
        deleted = self._store.delete_private(user_id=user_id, team_id=team_id)
        return (
            f"已取消战队订阅：{team_id}。"
            if deleted
            else f"你没有订阅战队：{team_id}。"
        )

    def answer_prompt(
        self,
        *,
        group_id: int,
        user_id: int,
        accepted: bool,
    ) -> str | None:
        prompt = self._store.get_pending_prompt(group_id)
        if prompt is None:
            return None
        self._store.mark_prompt_handled(
            group_id=group_id,
            handled_by=user_id,
            accepted=accepted,
        )
        if not accepted:
            return (
                "已跳过本群战队订阅提示。以后需要时，群主/管理员仍可发送"
                "“订阅战队123456”添加。"
            )

        at_user_ids = self.default_at_user_ids
        result = TeamResourceResult(
            prompt.team_id,
            prompt.team_name,
            "",
            0,
        )
        self._save_subscription(
            group_id=group_id,
            result=result,
            threshold=self._config.default_threshold,
            at_user_ids=at_user_ids,
            operator_id=user_id,
        )
        label = prompt.team_name or str(prompt.team_id)
        return (
            f"已订阅本群战队：{label}（{prompt.team_id}）。\n"
            f"资源阈值：{self._config.default_threshold}\n"
            f"提醒对象：{_format_user_ids(at_user_ids)}\n"
            "还可以继续发送“订阅战队123456”添加更多战队。"
        )

    async def query_group_messages(self, group_id: int) -> list[str]:
        return await self.query_messages(
            (
                subscription.team_id
                for subscription in self._store.list_group(group_id)
            ),
            group_id=group_id,
        )

    async def query_private_messages(self, user_id: int) -> list[str]:
        return await self.query_messages(
            (
                subscription.team_id
                for subscription in self._store.list_user(user_id)
            ),
        )

    async def query_messages(
        self,
        team_ids: Iterable[int],
        *,
        group_id: int | None = None,
    ) -> list[str]:
        return [
            await self._query_message(team_id, group_id=group_id)
            for team_id in team_ids
        ]

    async def query(
        self,
        team_id: int,
        *,
        group_id: int | None = None,
    ) -> TeamResourceResult:
        if not is_valid_team_id(team_id):
            raise TeamResourceQueryError(TEAM_ID_ERROR_MESSAGE)
        try:
            return await asyncio.wait_for(
                self._fetch(team_id, group_id=group_id),
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
        for subscription in self._store.list_all():
            if not self._features.group_has_feature(
                subscription.group_id,
                TEAM_RESOURCE_FEATURE,
            ):
                continue
            try:
                result = await self.query(
                    subscription.team_id,
                    group_id=subscription.group_id,
                )
            except TeamResourceQueryError:
                continue

            self._store.update_team_name(
                group_id=subscription.group_id,
                team_id=subscription.team_id,
                team_name=result.team_name,
            )
            if result.resource >= subscription.threshold:
                continue
            await self._delivery.send_targets(
                [
                    MessageTarget(
                        "group",
                        subscription.group_id,
                        subscription.at_user_ids,
                    )
                ],
                self._resource_notice(result, subscription),
                action_name="team resource subscription notice",
                interval_seconds=0,
            )

        for subscription in self._store.list_all_private():
            if not self._features.user_has_feature(
                subscription.user_id,
                TEAM_RESOURCE_FEATURE,
            ):
                continue
            try:
                result = await self.query(subscription.team_id)
            except TeamResourceQueryError:
                continue

            self._store.update_private_team_name(
                user_id=subscription.user_id,
                team_id=subscription.team_id,
                team_name=result.team_name,
            )
            if result.resource >= subscription.threshold:
                continue
            await self._delivery.send_targets(
                [MessageTarget("private", subscription.user_id)],
                self._resource_notice(result, subscription),
                action_name="private team resource subscription notice",
                interval_seconds=0,
            )

    def register_jobs(self, scheduler: Scheduler) -> None:
        if not self.enabled:
            return
        jobs = JobRegistry(scheduler, prefix=TEAM_RESOURCE_JOB_PREFIX)
        scan = self.scan
        for time_text in self._config.times:
            hour_text, minute_text = time_text.split(":", maxsplit=1)
            jobs.add(
                scan,
                "cron",
                hour=int(hour_text),
                minute=int(minute_text),
                job_id=time_text.replace(":", ""),
            )

    async def _fetch(
        self,
        team_id: int,
        *,
        group_id: int | None,
    ) -> TeamResourceResult:
        try:
            game = self._headless.get_game()
            with game.operations.track(
                "战队资源查询",
                f"战队 {team_id}",
                source="战队资源查询",
                background=True,
                group_id=group_id,
            ):
                info = await game.get_team_info(team_id)
        except (NotLoggedInError, DisconnectedError) as error:
            await self._headless.mark_unavailable(
                str(error),
                source="战队资源查询",
            )
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
        *,
        group_id: int | None,
    ) -> str:
        try:
            return (await self.query(team_id, group_id=group_id)).message
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

    def _save_subscription(
        self,
        *,
        group_id: int,
        result: TeamResourceResult,
        threshold: int,
        at_user_ids: tuple[int, ...],
        operator_id: int,
    ) -> None:
        self._store.upsert(
            TeamResourceSubscriptionUpdate(
                group_id=group_id,
                team_id=result.team_id,
                team_name=result.team_name,
                threshold=threshold,
                at_user_ids=at_user_ids,
                operator_id=operator_id,
            )
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
def _format_user_ids(user_ids: tuple[int, ...]) -> str:
    return "、".join(str(user_id) for user_id in user_ids) if user_ids else "无"
