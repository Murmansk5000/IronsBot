# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_cache_messages import (
    build_local_rank_cache_status_message,
    build_local_rank_refresh_empty_message,
    build_local_rank_refresh_result_message,
    build_local_rank_refresh_start_message,
    build_rank_batch_no_players_message,
    build_rank_batch_result_message,
    build_rank_batch_start_message,
)
from ironsbot.services.seer.rank_page_cache_messages import (
    build_rank_page_cache_overview_message,
    build_rank_page_cache_status_message,
    build_rank_page_refresh_result_message,
    build_rank_page_refresh_start_message,
)
from ironsbot.services.seer.rank_page_refresh_selection import (
    configured_rank_specs,
    filter_standard_rank_page_summaries,
    rank_refresh_target_label,
    rank_target_limit,
)

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.operations.headless import (
        HeadlessGame,
        HeadlessService,
    )
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )
    from ironsbot.services.seer.rank import RankService
    from ironsbot.services.seer.rank_list_models import (
        GlobalRankSpec,
        RankCacheBatchCommand,
        RankPageCacheRefreshCommand,
        RankPageCacheStatusCommand,
    )
    from ironsbot.services.seer.rank_page_refresh import RankPageRefreshService

ProgressReporter = Callable[[str], Awaitable[None]]
@dataclass(frozen=True, slots=True)
class RankAdminPolicy:
    rank_limit: int
    batch_limit: int
    refresh_limit: int
    refresh_max_age_hours: int
    page_cache_ttl_seconds: int
    display_limit: Callable[[ConversationRef | None], int]


class RankAdminService:
    def __init__(  # noqa: PLR0913 - composed runtime dependencies
        self,
        policy: RankAdminPolicy,
        rank: RankService,
        local_rank: LocalRankService,
        page_refresh: RankPageRefreshService,
        headless: HeadlessService,
        requests: PlayerRequestProtectionService,
    ) -> None:
        self._policy = policy
        self._rank = rank
        self._local_rank = local_rank
        self._page_refresh = page_refresh
        self._headless = headless
        self._requests = requests

    async def cache_batch(
        self,
        command: RankCacheBatchCommand,
        *,
        actor: ActorRef,
        progress: ProgressReporter,
    ) -> str:
        spec = self._rank.get_spec(command.rank_key)
        requested_count = command.end_rank - command.start_rank + 1
        if self._rank.spec_needs_sub_key(spec):
            return build_rank_batch_no_players_message(spec)
        request_count = min(requested_count, self._policy.batch_limit)
        await progress(
            build_rank_batch_start_message(
                spec,
                command,
                request_count=request_count,
                requested_count=requested_count,
            )
        )
        item_count = await self._requests.run(
            lambda: self._cache_global_batch(
                self._headless.get_game(),
                command,
                spec=spec,
                request_count=request_count,
            ),
            actor=actor,
            label="手动缓存榜单",
        )
        if item_count <= 0:
            return build_rank_batch_no_players_message(spec)
        return build_rank_batch_result_message(
            spec,
            command,
            item_count=item_count,
            requested_count=requested_count,
        )

    def page_status(self, command: RankPageCacheStatusCommand) -> str:
        spec = self._rank.get_spec(command.rank_key)
        refresh = self._page_refresh
        pages = filter_standard_rank_page_summaries(
            spec,
            self._rank.cache.summary(key=spec.key, sub_key=spec.sub_key),
            config=refresh.config,
            rank_key=command.rank_key,
        )
        targets = refresh.preview([command.rank_key])
        return build_rank_page_cache_status_message(
            spec,
            pages,
            ttl_seconds=self._policy.page_cache_ttl_seconds,
            target_limit=rank_target_limit(
                refresh.config,
                command.rank_key,
            ),
            target_label=rank_refresh_target_label(
                refresh.config,
                command.rank_key,
            ),
            next_ranges=[
                (target.reason, target.start_rank, target.end_rank)
                for target in targets[:5]
            ],
        )

    def page_overview(self) -> str:
        refresh = self._page_refresh
        specs = configured_rank_specs(refresh.config, self._rank)
        targets = refresh.preview()
        targets_by_rank = {
            rank_key: [
                target
                for target in targets
                if target.rank_key == rank_key
            ]
            for rank_key, _spec in specs
        }
        entries = [
            (
                rank_key,
                spec,
                filter_standard_rank_page_summaries(
                    spec,
                    self._rank.cache.summary(
                        key=spec.key,
                        sub_key=spec.sub_key,
                    ),
                    config=refresh.config,
                    rank_key=rank_key,
                ),
                targets_by_rank.get(rank_key, ()),
                rank_target_limit(refresh.config, rank_key),
                rank_refresh_target_label(refresh.config, rank_key),
            )
            for rank_key, spec in specs
        ]
        return build_rank_page_cache_overview_message(entries)

    async def page_refresh(
        self,
        command: RankPageCacheRefreshCommand,
        *,
        actor: ActorRef,
        progress: ProgressReporter,
    ) -> str:
        await progress(build_rank_page_refresh_start_message(command))
        rank_keys = None if command.rank_key is None else [command.rank_key]
        result = await self._page_refresh.refresh(
            self._headless.get_game,
            rank_keys,
            actor=actor,
        )
        return build_rank_page_refresh_result_message(result)

    def cache_status(self, conversation: ConversationRef | None) -> str:
        policy = self._policy
        return build_local_rank_cache_status_message(
            self._local_rank.stats(),
            rank_limit=policy.rank_limit,
            batch_limit=policy.batch_limit,
            refresh_limit=policy.refresh_limit,
            refresh_max_age_hours=policy.refresh_max_age_hours,
            display_limit=policy.display_limit(conversation),
        )

    async def cache_refresh(
        self,
        *,
        actor: ActorRef,
        progress: ProgressReporter,
    ) -> str:
        before = self._local_rank.stats()
        if before.player_count <= 0:
            return build_local_rank_refresh_empty_message()
        await progress(
            build_local_rank_refresh_start_message(
                before,
                refresh_limit=self._policy.refresh_limit,
                refresh_max_age_hours=self._policy.refresh_max_age_hours,
            )
        )
        result = await self._local_rank.refresh(
            self._headless.get_game,
            actor=actor,
        )
        return build_local_rank_refresh_result_message(
            result,
            self._local_rank.stats(),
        )

    async def _cache_global_batch(
        self,
        game: HeadlessGame,
        command: RankCacheBatchCommand,
        *,
        spec: GlobalRankSpec,
        request_count: int,
    ) -> int:
        with game.operations.track(
            "手动缓存榜单",
            f"{spec.title} 第 {command.start_rank}-{command.end_rank}名",
            source="手动缓存榜单",
        ):
            items = await self._rank.fetch_range(
                game,
                key=spec.key,
                sub_key=spec.sub_key,
                start=command.start_rank - 1,
                count=request_count,
                use_cache=False,
            )
        return len(items)
