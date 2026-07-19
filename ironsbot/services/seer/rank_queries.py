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
from ironsbot.services.seer.rank_usage import build_rank_help_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.services.operations.headless import (
        HeadlessGame,
        HeadlessService,
    )
    from ironsbot.services.seer.local_rank import LocalRankService
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
    def __init__(
        self,
        rank: RankService,
        local_rank: LocalRankService,
        display: RankDisplayService,
        headless: HeadlessService,
        policy: RankQueryPolicy,
    ) -> None:
        self._rank = rank
        self._local_rank = local_rank
        self._display = display
        self._headless = headless
        self._policy = policy

    @staticmethod
    def help_message() -> str:
        return build_rank_help_message()

    def default_limit(self, group_id: int | None) -> int:
        return self._display.limit_for_group(group_id)

    async def list(self, command: RankListCommand) -> str:
        if command.kind == "local":
            return self._local_message(command)
        return await self._global_message(
            self._headless.get_game(),
            command,
        )

    async def score(
        self,
        command: RankScoreCommand,
        *,
        group_id: int | None,
    ) -> str:
        return await self._score_message(
            self._headless.get_game(),
            command,
            display_limit=self.default_limit(group_id),
        )

    async def player(self, command: RankPlayerCommand) -> str:
        spec = GLOBAL_RANKS[command.rank_key]
        try:
            return await asyncio.wait_for(
                self._player_message(
                    self._headless.get_game(),
                    command,
                ),
                timeout=self._policy.player_timeout_seconds,
            )
        except TimeoutError:
            return f"❌ {spec.title}玩家查询超时，请稍后再试。"
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return self._policy.player_error(command.player_id, error)
        except Exception as error:  # noqa: BLE001
            return f"❌ {spec.title}玩家查询失败：{error}"

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
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        if self._rank.spec_needs_sub_key(spec):
            return "❌找不到当前巅峰赛季数据。"
        with game.operations.track(
            "榜单分数查询",
            f"{spec.title} {command.score}{spec.unit}",
            source="榜单分数查询",
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
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        with game.operations.track(
            "榜单玩家查询",
            f"{spec.title} 米米号 {command.player_id}",
            source="榜单玩家查询",
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
