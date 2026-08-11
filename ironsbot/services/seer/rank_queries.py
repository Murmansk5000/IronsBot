# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.ids import (
    PLAYER_ID_ERROR_MESSAGE,
    is_valid_player_id,
)
from ironsbot.services.seer.player_query_limits import (
    PlayerQueryQuotaExceededError,
)
from ironsbot.services.seer.player_request_protection import (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
    player_request_protection_message,
)
from ironsbot.services.seer.query_result import QueryReply
from ironsbot.services.seer.query_work import (
    QueryWorkMeter,
    query_work_scope,
    record_rank_lookup_work,
)
from ironsbot.services.seer.rank_list_formatting import timestamp_text
from ironsbot.services.seer.rank_list_global_messages import (
    format_global_rank_message,
)
from ironsbot.services.seer.rank_list_messages import format_local_rank_message
from ironsbot.services.seer.rank_list_models import (
    GLOBAL_RANKS,
    LOCAL_RANKS,
)
from ironsbot.services.seer.rank_list_score_messages import (
    format_global_rank_score_message,
)
from ironsbot.services.seer.rank_player_query import (
    RankPlayerQueryResult,
    fetch_cached_rank_player_result,
    fetch_rank_player_result,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.operations.headless import (
        HeadlessGame,
        HeadlessService,
    )
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_query_limits import PlayerQueryQuotaService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_display import RankDisplayService
    from ironsbot.services.seer.rank_list_models import (
        RankListCommand,
        RankPlayerCommand,
        RankScoreCommand,
    )

    PlayerErrorFormatter = Callable[
        [int, SocketRecvError | NotLoggedInError | DisconnectedError],
        str,
    ]

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RankQueryPolicy:
    player_error: PlayerErrorFormatter
    player_timeout_seconds: float


class RankQueryService:
    def __init__(  # noqa: PLR0913 - composed rank query dependencies
        self,
        rank: RankService,
        local_rank: LocalRankService,
        display: RankDisplayService,
        headless: HeadlessService,
        policy: RankQueryPolicy,
        quotas: PlayerQueryQuotaService | None = None,
        requests: PlayerRequestProtectionService | None = None,
    ) -> None:
        self._rank = rank
        self._local_rank = local_rank
        self._display = display
        self._headless = headless
        self._policy = policy
        self._quotas = quotas
        self._requests = requests

    def default_limit(self, group_id: int | None) -> int:
        return self._display.limit_for_group(group_id)

    async def list(
        self,
        command: RankListCommand,
        *,
        qq_user_id: int | None = None,
        group_id: int | None = None,
    ) -> str:
        return (
            await self.list_reply(
                command,
                qq_user_id=qq_user_id,
                group_id=group_id,
            )
        ).text

    async def list_reply(
        self,
        command: RankListCommand,
        *,
        qq_user_id: int | None = None,
        group_id: int | None = None,
    ) -> QueryReply:
        if command.kind == "local":
            return QueryReply(text=self._local_message(command))
        quota_message = self._check_general_quota(
            qq_user_id,
            action_key=f"rank:list:{command.rank_key}",
        )
        if quota_message:
            return self._cached_list_reply(command) or QueryReply(text=quota_message)
        meter = QueryWorkMeter("foreground")
        try:
            text = await self._run_headless_request(
                lambda: self._global_message_with_work(
                    meter,
                    self._headless.get_game(),
                    command,
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单查询",
            )
        except _PLAYER_REQUEST_ERRORS as error:
            return QueryReply(text=player_request_protection_message(error))
        return QueryReply(text=text, query_work=meter.result())

    async def score(
        self,
        command: RankScoreCommand,
        *,
        group_id: int | None,
        qq_user_id: int | None = None,
    ) -> str:
        return (
            await self.score_reply(
                command,
                group_id=group_id,
                qq_user_id=qq_user_id,
            )
        ).text

    async def score_reply(
        self,
        command: RankScoreCommand,
        *,
        group_id: int | None,
        qq_user_id: int | None = None,
    ) -> QueryReply:
        quota_message = self._check_general_quota(
            qq_user_id,
            action_key=f"rank:score:{command.rank_key}",
        )
        if quota_message:
            return self._cached_score_reply(
                command,
                display_limit=self.default_limit(group_id),
            ) or QueryReply(text=quota_message)
        meter = QueryWorkMeter("foreground")
        try:
            text = await self._run_headless_request(
                lambda: self._score_message_with_work(
                    meter,
                    self._headless.get_game(),
                    command,
                    display_limit=self.default_limit(group_id),
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单分数查询",
            )
        except _PLAYER_REQUEST_ERRORS as error:
            return QueryReply(text=player_request_protection_message(error))
        return QueryReply(text=text, query_work=meter.result())

    async def player_reply(  # noqa: PLR0911 - distinct query failure replies
        self,
        command: RankPlayerCommand,
        *,
        qq_user_id: int | None = None,
        group_id: int | None = None,
    ) -> QueryReply:
        spec = GLOBAL_RANKS[command.rank_key]
        if not is_valid_player_id(command.player_id):
            return QueryReply(text=PLAYER_ID_ERROR_MESSAGE)
        quota_message = self._check_player_quota(command, qq_user_id)
        if quota_message:
            return self._cached_player_reply(command) or QueryReply(text=quota_message)
        meter = QueryWorkMeter("foreground")
        try:
            result = await self._run_headless_request(
                lambda: self._fetch_player_message_with_work(
                    meter,
                    command,
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单玩家查询",
                semantic_request=SemanticRequest(
                    action=ActionDefinition(
                        f"seer.rank.player.{command.rank_key}",
                        f"{spec.title}玩家查询",
                    ),
                    target=SemanticTarget(
                        key=str(command.player_id),
                        display=f"米米号 {command.player_id}",
                    ),
                    source=SemanticRequestSource.DIRECT,
                ),
            )
        except PlayerQueryQuotaExceededError as error:
            return QueryReply(text=error.message)
        except _PLAYER_REQUEST_ERRORS as error:
            return QueryReply(text=player_request_protection_message(error))
        except TimeoutError:
            return QueryReply(text=f"❌ {spec.title}玩家查询超时，请稍后再试。")
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return QueryReply(text=self._policy.player_error(command.player_id, error))
        except Exception as error:  # noqa: BLE001
            return QueryReply(text=f"❌ {spec.title}玩家查询失败：{error}")
        return QueryReply(text=result.message, query_work=meter.result())

    async def player(
        self,
        command: RankPlayerCommand,
        *,
        qq_user_id: int | None = None,
        group_id: int | None = None,
    ) -> str:
        """Compatibility text API for non-OneBot callers."""

        return (
            await self.player_reply(
                command,
                qq_user_id=qq_user_id,
                group_id=group_id,
            )
        ).text

    def record_returned_player(
        self,
        command: RankPlayerCommand,
        qq_user_id: int | None,
        reply: QueryReply,
    ) -> None:
        if self._quotas is None or qq_user_id is None or reply.query_work is None:
            return
        self._quotas.record_successful_work(
            qq_user_id=qq_user_id,
            player_id=command.player_id,
            action_key=f"rank:{command.rank_key}",
            units=reply.query_work.billable_units,
        )

    def record_returned_general_reply(
        self,
        *,
        qq_user_id: int | None,
        action_key: str,
        reply: QueryReply,
    ) -> None:
        if self._quotas is None or qq_user_id is None or reply.query_work is None:
            return
        self._quotas.record_general_work(
            qq_user_id=qq_user_id,
            action_key=action_key,
            units=reply.query_work.billable_units,
        )

    async def _global_message_with_work(
        self,
        meter: QueryWorkMeter,
        game: HeadlessGame,
        command: RankListCommand,
        *,
        group_id: int | None,
    ) -> str:
        with query_work_scope(meter):
            return await self._global_message(game, command, group_id=group_id)

    async def _score_message_with_work(
        self,
        meter: QueryWorkMeter,
        game: HeadlessGame,
        command: RankScoreCommand,
        *,
        display_limit: int,
        group_id: int | None,
    ) -> str:
        with query_work_scope(meter):
            return await self._score_message(
                game,
                command,
                display_limit=display_limit,
                group_id=group_id,
            )

    async def _fetch_player_message(
        self,
        command: RankPlayerCommand,
        *,
        group_id: int | None,
    ) -> RankPlayerQueryResult:
        result = await asyncio.wait_for(
            self._player_message(
                self._headless.get_game(),
                command,
                group_id=group_id,
                anchor_only=False,
            ),
            timeout=self._policy.player_timeout_seconds,
        )
        record_rank_lookup_work(command.rank_key, result.lookup)
        return result

    async def _fetch_player_message_with_work(
        self,
        meter: QueryWorkMeter,
        command: RankPlayerCommand,
        *,
        group_id: int | None,
    ) -> RankPlayerQueryResult:
        with query_work_scope(meter):
            return await self._fetch_player_message(command, group_id=group_id)

    def set_display_limit(
        self,
        *,
        group_id: int | None,
        user_id: int,
        can_manage: bool,
        limit: int,
    ) -> str:
        if group_id is None:
            return "❌ 这个设置只能在群聊中修改。"
        if not can_manage:
            return "❌ 只有群主、管理员或超级管理员可以修改榜单默认显示条数。"
        max_limit = self._display.config.max_display_limit
        if limit < 1 or limit > max_limit:
            return f"❌ 榜单默认显示条数必须在 1~{max_limit} 之间，当前输入：{limit}。"
        self._display.set_group_limit(group_id, user_id, limit)
        return f"✅ 榜单默认显示条数已设置为 {limit} 名（群号：{group_id}）。"

    async def _global_message(
        self,
        game: HeadlessGame,
        command: RankListCommand,
        *,
        group_id: int | None,
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        if self._rank.spec_needs_sub_key(spec):
            return "❌找不到当前巅峰赛季数据。"
        with game.operations.track(
            "榜单查询",
            (
                f"{spec.title} 第 "
                f"{command.start_rank}-{command.start_rank + command.limit - 1}名"
            ),
            source="榜单查询",
            group_id=group_id,
        ):
            result = await self._rank.fetch_visible_range_result(
                game,
                rank_key=command.rank_key,
                key=spec.key,
                sub_key=spec.sub_key,
                start_rank=command.start_rank,
                count=command.limit,
            )
        return format_global_rank_message(
            spec,
            result.items,
            timestamp=timestamp_text(result.fetched_at),
            start_rank=command.start_rank,
            requested_count=command.limit,
        )

    async def _score_message(
        self,
        game: HeadlessGame,
        command: RankScoreCommand,
        *,
        display_limit: int,
        group_id: int | None,
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        if self._rank.spec_needs_sub_key(spec):
            return "❌找不到当前巅峰赛季数据。"
        with game.operations.track(
            "榜单分数查询",
            f"{spec.title} {command.score}{spec.unit}",
            source="榜单分数查询",
            group_id=group_id,
        ):
            result = await self._rank.fetch_score_segment(
                game,
                key=spec.key,
                sub_key=spec.sub_key,
                title=spec.title,
                score_name=spec.unit,
                target_score=command.score,
                rank_key=command.rank_key,
                sample_limit=display_limit,
            )
        logger.info(
            "rank score lookup completed: title=%s key=%s sub_key=%s "
            "score=%s items=%s total=%s boundary=%s searched_limit=%s "
            "truncated=%s",
            spec.title,
            spec.key,
            spec.sub_key,
            command.score,
            len(result.items),
            result.total_count,
            result.boundary_score,
            result.searched_limit,
            result.truncated,
        )
        return format_global_rank_score_message(
            spec,
            result,
            timestamp=(
                timestamp_text(result.fetched_at) if result.fetched_at else None
            ),
            display_limit=display_limit,
        )

    async def _player_message(
        self,
        game: HeadlessGame,
        command: RankPlayerCommand,
        *,
        group_id: int | None,
        anchor_only: bool,
    ) -> RankPlayerQueryResult:
        spec = self._rank.get_spec(command.rank_key)
        with game.operations.track(
            "榜单玩家查询",
            f"{spec.title} 米米号 {command.player_id}",
            source="榜单玩家查询",
            group_id=group_id,
        ):
            return await fetch_rank_player_result(
                self._rank,
                self._local_rank,
                game,
                command=command,
                anchor_only=anchor_only,
            )

    def _local_message(self, command: RankListCommand) -> str:
        spec = LOCAL_RANKS[command.rank_key]
        season_sub_key = (
            self._rank.current_peak_sub_key() if spec.season_limited else None
        )
        entries, sample_count = self._local_rank.entries(
            spec.metric_key,
            limit=command.limit,
            start_rank=command.start_rank,
            season_sub_key=season_sub_key,
        )
        return format_local_rank_message(
            spec,
            entries,
            sample_count=sample_count,
            season_sub_key=(
                str(season_sub_key) if season_sub_key is not None else None
            ),
            start_rank=command.start_rank,
            requested_count=command.limit,
        )

    def _cached_list_reply(self, command: RankListCommand) -> QueryReply | None:
        spec = self._rank.get_spec(command.rank_key)
        if self._rank.spec_needs_sub_key(spec):
            return None
        result = self._rank.cached_visible_range_result(
            rank_key=command.rank_key,
            key=spec.key,
            sub_key=spec.sub_key,
            start_rank=command.start_rank,
            count=command.limit,
        )
        if result is None:
            return None
        return QueryReply(
            text=_cache_only_message(
                format_global_rank_message(
                    spec,
                    result.items,
                    timestamp=timestamp_text(result.fetched_at),
                    start_rank=command.start_rank,
                    requested_count=command.limit,
                )
            )
        )

    def _cached_score_reply(
        self,
        command: RankScoreCommand,
        *,
        display_limit: int,
    ) -> QueryReply | None:
        spec = self._rank.get_spec(command.rank_key)
        if self._rank.spec_needs_sub_key(spec):
            return None
        result = self._rank.cached_score_segment(
            rank_key=command.rank_key,
            key=spec.key,
            sub_key=spec.sub_key,
            title=spec.title,
            score_name=spec.unit,
            target_score=command.score,
            sample_limit=display_limit,
        )
        if result is None:
            return None
        return QueryReply(
            text=_cache_only_message(
                format_global_rank_score_message(
                    spec,
                    result,
                    timestamp=(
                        timestamp_text(result.fetched_at) if result.fetched_at else None
                    ),
                    display_limit=display_limit,
                )
            )
        )

    def _cached_player_reply(
        self,
        command: RankPlayerCommand,
    ) -> QueryReply | None:
        cached = fetch_cached_rank_player_result(self._rank, command=command)
        if cached is None:
            return None
        return QueryReply(text=_cache_only_message(cached.message))

    def _check_player_quota(
        self,
        command: RankPlayerCommand,
        qq_user_id: int | None,
    ) -> str:
        if self._quotas is None or qq_user_id is None:
            return ""
        decision = self._quotas.check(
            qq_user_id=qq_user_id,
            player_id=command.player_id,
            action_key=f"rank:{command.rank_key}",
        )
        return "" if decision.allowed else decision.message

    def _check_general_quota(
        self,
        qq_user_id: int | None,
        *,
        action_key: str,
    ) -> str:
        if self._quotas is None or qq_user_id is None:
            return ""
        decision = self._quotas.check_general_query(
            qq_user_id=qq_user_id,
            action_key=action_key,
        )
        return "" if decision.allowed else decision.message

    def _record_player_quota(
        self,
        command: RankPlayerCommand,
        qq_user_id: int | None,
    ) -> str:
        if self._quotas is None or qq_user_id is None:
            return ""
        decision = self._quotas.consume(
            qq_user_id=qq_user_id,
            player_id=command.player_id,
            action_key=f"rank:{command.rank_key}",
        )
        return "" if decision.allowed else decision.message

    def _record_successful_player_quota(
        self,
        command: RankPlayerCommand,
        qq_user_id: int | None,
    ) -> None:
        quota_message = self._record_player_quota(command, qq_user_id)
        if quota_message:
            logger.warning(
                "rank player quota changed before successful record: "
                "user=%s player=%s rank_key=%s",
                qq_user_id,
                command.player_id,
                command.rank_key,
            )

    async def _run_headless_request(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        user_id: int | None,
        label: str,
        semantic_request: SemanticRequest | None = None,
    ) -> T:
        if self._requests is None:
            return await operation()
        return await self._requests.run(
            operation,
            user_id=user_id,
            label=label,
            semantic_request=semantic_request,
        )


_PLAYER_REQUEST_ERRORS = (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
)


def _cache_only_message(text: str) -> str:
    return f"{text}\n\n⚠️ 今日查询额度已用完，以上为缓存数据。"
