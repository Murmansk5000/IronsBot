# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
from ironsbot.services.seer.rank_list_formatting import (
    batch_raw_start,
    timestamp_text,
)
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
from ironsbot.services.seer.rank_player_query import fetch_rank_player_message

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
        if command.kind == "local":
            return self._local_message(command)
        try:
            return await self._run_headless_request(
                lambda: self._global_message(
                    self._headless.get_game(),
                    command,
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单查询",
            )
        except _PLAYER_REQUEST_ERRORS as error:
            return player_request_protection_message(error)

    async def score(
        self,
        command: RankScoreCommand,
        *,
        group_id: int | None,
        qq_user_id: int | None = None,
    ) -> str:
        try:
            return await self._run_headless_request(
                lambda: self._score_message(
                    self._headless.get_game(),
                    command,
                    display_limit=self.default_limit(group_id),
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单分数查询",
            )
        except _PLAYER_REQUEST_ERRORS as error:
            return player_request_protection_message(error)

    async def player(  # noqa: PLR0911 - distinct query failure replies
        self,
        command: RankPlayerCommand,
        *,
        qq_user_id: int | None = None,
        group_id: int | None = None,
    ) -> str:
        spec = GLOBAL_RANKS[command.rank_key]
        if not is_valid_player_id(command.player_id):
            return PLAYER_ID_ERROR_MESSAGE
        quota_message = self._check_player_quota(command, qq_user_id)
        if quota_message:
            return quota_message
        try:
            message = await self._run_headless_request(
                lambda: self._fetch_player_message(
                    command,
                    qq_user_id,
                    group_id=group_id,
                ),
                user_id=qq_user_id,
                label="榜单玩家查询",
            )
        except PlayerQueryQuotaExceededError as error:
            return error.message
        except _PLAYER_REQUEST_ERRORS as error:
            return player_request_protection_message(error)
        except TimeoutError:
            return f"❌ {spec.title}玩家查询超时，请稍后再试。"
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return self._policy.player_error(command.player_id, error)
        except Exception as error:  # noqa: BLE001
            return f"❌ {spec.title}玩家查询失败：{error}"
        self._record_successful_player_quota(command, qq_user_id)
        return message

    async def _fetch_player_message(
        self,
        command: RankPlayerCommand,
        qq_user_id: int | None,
        *,
        group_id: int | None,
    ) -> str:
        quota_message = self._check_player_quota(command, qq_user_id)
        if quota_message:
            raise PlayerQueryQuotaExceededError(quota_message)
        return await asyncio.wait_for(
            self._player_message(
                self._headless.get_game(),
                command,
                group_id=group_id,
            ),
            timeout=self._policy.player_timeout_seconds,
        )

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
            return "❌ 只有本群群主、管理员或超级管理员可以修改榜单默认显示条数。"
        max_limit = self._display.config.max_display_limit
        if limit < 1 or limit > max_limit:
            return (
                f"❌ 榜单默认显示条数必须在 1~{max_limit} 之间，"
                f"当前输入：{limit}。"
            )
        self._display.set_group_limit(group_id, user_id, limit)
        return (
            f"✅ 本群榜单默认显示条数已设置为 {limit} 名"
            f"（群号：{group_id}）。"
        )

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
            result = await self._rank.fetch_range_result(
                game,
                key=spec.key,
                sub_key=spec.sub_key,
                start=batch_raw_start(spec, command.start_rank),
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
                start_index=spec.start,
                rank_offset=spec.rank_offset,
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
                timestamp_text(result.fetched_at)
                if result.fetched_at
                else None
            ),
            display_limit=display_limit,
        )

    async def _player_message(
        self,
        game: HeadlessGame,
        command: RankPlayerCommand,
        *,
        group_id: int | None,
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        with game.operations.track(
            "榜单玩家查询",
            f"{spec.title} 米米号 {command.player_id}",
            source="榜单玩家查询",
            group_id=group_id,
        ):
            return await fetch_rank_player_message(
                self._rank,
                self._local_rank,
                game,
                command=command,
            )

    def _local_message(self, command: RankListCommand) -> str:
        spec = LOCAL_RANKS[command.rank_key]
        season_sub_key = (
            self._rank.current_peak_sub_key()
            if spec.season_limited
            else None
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
                str(season_sub_key)
                if season_sub_key is not None
                else None
            ),
            start_rank=command.start_rank,
            requested_count=command.limit,
        )

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
        operation: Callable[[], Awaitable[str]],
        *,
        user_id: int | None,
        label: str,
    ) -> str:
        if self._requests is None:
            return await operation()
        return await self._requests.run(
            operation,
            user_id=user_id,
            label=label,
        )


_PLAYER_REQUEST_ERRORS = (
    PlayerRequestBusyError,
    PlayerRequestPausedError,
    PlayerRequestReconnectError,
)
