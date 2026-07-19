# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_player_query_error
from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_binding import player_binding_offer_message
from ironsbot.services.seer.player_compact_formatting import (
    format_compact_player_info,
)
from ironsbot.services.seer.player_detail_formatting import (
    format_player_detail_messages,
)
from ironsbot.services.seer.player_query import (
    PlayerDetailErrors,
    PlayerDetailMessages,
    PlayerQuerySectionPlan,
    calculate_player_peak_scores,
    optional_player_extra,
    plan_player_detail_fetches,
    plan_player_query_sections,
    player_query_failure_message,
    player_query_timeout_message,
    validate_player_peak_season,
)
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    fetch_player_shortcut_message,
)
from ironsbot.services.seer.rank_models import (
    PeakSeasonRankSummary,
    PlayerRankSummary,
    RankLookupResult,
    RankSummaryProgress,
)
from ironsbot.services.seer.sequ_extra import (
    UnityPartOneInfo,
    UnityPeakInfo,
    fetch_unity_part_one,
    fetch_unity_peak,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ironsbot.config.models.seer import SeerConfig
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.operations.headless import (
        HeadlessGame,
        HeadlessService,
    )
    from ironsbot.services.seer.errors import ErrorMessageLookup
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_binding import PlayerBindingStore
    from ironsbot.services.seer.rank import RankService

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(slots=True)
class PendingPlayerQuery:
    player_id: int
    game: HeadlessGame
    user_info: Any
    more_info: Any
    player_message: str
    section_plan: PlayerQuerySectionPlan


@dataclass(frozen=True, slots=True)
class PlayerQueryResult:
    pending: PendingPlayerQuery | None = None
    message: str = ""
    offer_binding: bool = False


class PlayerDetailService:
    def __init__(
        self,
        config: SeerConfig,
        rank: RankService,
        local_rank: LocalRankService,
        spawn: TaskSpawner,
    ) -> None:
        self._config = config
        self._rank = rank
        self._local_rank = local_rank
        self._spawn = spawn

    def create_task(
        self,
        pending: PendingPlayerQuery,
    ) -> asyncio.Task[PlayerDetailMessages] | None:
        plan = pending.section_plan
        if not plan.needs_detail_task:
            return None
        task = self._spawn(
            self._build_messages(
                game=pending.game,
                player_id=pending.player_id,
                user_info=pending.user_info,
                more_info=pending.more_info,
                has_collection=plan.has_collection,
                needs_peak_section=plan.needs_peak_section,
                has_autocard_rank=plan.has_autocard_rank,
                show_local_rank=plan.show_local_rank,
            ),
            name=f"seer-player-detail-{pending.player_id}",
        )
        task.add_done_callback(self._log_unrequested_task_error)
        return task

    async def shortcut(
        self,
        game: HeadlessGame,
        command: PlayerShortcutCommand,
        player_id: int,
    ) -> str:
        return await fetch_player_shortcut_message(
            self._rank,
            self._local_rank,
            game,
            command=command,
            player_id=player_id,
        )

    def spawn_task(
        self,
        coroutine: Coroutine[Any, Any, T],
        *,
        name: str,
    ) -> asyncio.Task[T]:
        return self._spawn(coroutine, name=name)

    async def _build_messages(  # noqa: PLR0913
        self,
        *,
        game: HeadlessGame,
        player_id: int,
        user_info: Any,
        more_info: Any,
        has_collection: bool,
        needs_peak_section: bool,
        has_autocard_rank: bool,
        show_local_rank: bool,
    ) -> PlayerDetailMessages:
        config = self._config
        extra_errors = PlayerDetailErrors()
        timeout_seconds = min(
            float(config.player.timeout_seconds),
            float(config.player.detail_timeout_seconds),
        )
        fetch_plan = plan_player_detail_fetches(
            has_collection=has_collection,
            needs_peak_section=needs_peak_section,
            has_autocard_rank=has_autocard_rank,
            local_rank_enabled=config.local_rank.enabled,
        )
        with game.operations.track(
            "米米号详情查询",
            f"米米号 {player_id}",
            source="米米号详情查询",
        ):
            unity_part_one, unity_peak = await asyncio.gather(
                optional_player_extra(
                    "展示/收集数据",
                    fetch_plan.needs_unity_part_one,
                    lambda: fetch_unity_part_one(game, player_id),
                    UnityPartOneInfo(),
                    extra_errors.collection,
                    on_error=self._log_extra_error,
                    timeout_seconds=timeout_seconds,
                ),
                optional_player_extra(
                    "巅峰数据",
                    fetch_plan.needs_unity_peak,
                    lambda: fetch_unity_peak(game, player_id),
                    UnityPeakInfo(),
                    extra_errors.peak,
                    on_error=self._log_extra_error,
                    timeout_seconds=timeout_seconds,
                ),
            )
            peak_sub_key = self._rank.current_peak_sub_key()
            peak_scores = calculate_player_peak_scores(unity_peak)
            rank_progress = RankSummaryProgress()
            peak_progress = RankSummaryProgress()
            rank_summary, peak_summary, autocard_summary = await asyncio.gather(
                optional_player_extra(
                    "全服排行",
                    fetch_plan.needs_rank_summary,
                    lambda: self._rank.fetch_player_summary(
                        game,
                        player_id,
                        achieve_score=getattr(
                            more_info,
                            "total_achieve",
                            None,
                        ),
                        pet_kind_count=unity_part_one.pet_kind_num,
                        skin_score=unity_part_one.skin_num,
                        progress=rank_progress,
                    ),
                    PlayerRankSummary.empty(),
                    extra_errors.collection,
                    on_error=self._log_extra_error,
                    timeout_seconds=timeout_seconds,
                    error_label_factory=lambda: (
                        rank_progress.current_title or "全服排行"
                    ),
                ),
                optional_player_extra(
                    "巅峰赛季榜",
                    needs_peak_section,
                    lambda: self._rank.fetch_peak_summary(
                        game,
                        player_id,
                        standard_score=peak_scores.standard,
                        wild_score=peak_scores.wild,
                        expert_score=peak_scores.expert,
                        progress=peak_progress,
                    ),
                    PeakSeasonRankSummary.empty(),
                    extra_errors.peak,
                    on_error=self._log_extra_error,
                    timeout_seconds=timeout_seconds,
                    error_label_factory=lambda: (
                        peak_progress.current_title or "巅峰赛季榜"
                    ),
                ),
                optional_player_extra(
                    "群星牌排行",
                    fetch_plan.needs_autocard_rank,
                    lambda: self._rank.fetch_autocard_summary(
                        game,
                        player_id,
                    ),
                    RankLookupResult(title="群星之巅榜", score_name="分"),
                    extra_errors.autocard,
                    on_error=self._log_extra_error,
                    timeout_seconds=timeout_seconds,
                ),
            )
            extra_errors.collection.extend(rank_summary.errors)
            extra_errors.peak.extend(peak_summary.errors)
            validated_peak = validate_player_peak_season(
                unity_peak,
                peak_scores,
                peak_summary,
            )
            local_summary = await optional_player_extra(
                "机器人查询排行",
                fetch_plan.needs_local_rank,
                lambda: self._local_rank.update_cache(
                    player_id=player_id,
                    nick=user_info.nick,
                    more_info=more_info,
                    unity_part_one=unity_part_one,
                    unity_peak=validated_peak.unity_peak,
                    rank_summary=rank_summary,
                    autocard_rank_summary=autocard_summary,
                    peak_sub_key=peak_sub_key,
                    peak_standard_score=validated_peak.scores.standard,
                    peak_wild_score=validated_peak.scores.wild,
                    peak_expert_score=validated_peak.scores.expert,
                    clear_metric_keys=validated_peak.clear_metric_keys,
                ),
                LocalRankSummary(),
                extra_errors.shared,
                on_error=self._log_extra_error,
                timeout_seconds=timeout_seconds,
            )
        return format_player_detail_messages(
            player_id=player_id,
            user_info=user_info,
            more_info=more_info,
            unity_part_one=unity_part_one,
            unity_peak=unity_peak,
            rank_summary=rank_summary,
            peak_rank_summary=peak_summary,
            autocard_rank_summary=autocard_summary,
            local_rank_summary=local_summary,
            empty_local_rank_summary=LocalRankSummary(),
            has_collection=has_collection,
            needs_peak_section=needs_peak_section,
            has_autocard_rank=has_autocard_rank,
            show_local_rank=show_local_rank,
            extra_errors=extra_errors,
        )

    @staticmethod
    def _log_extra_error(label: str, _error: Exception) -> None:
        logger.exception("米米号扩展字段获取失败：%s", label)

    @staticmethod
    def _log_unrequested_task_error(
        task: asyncio.Task[PlayerDetailMessages],
    ) -> None:
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error(
                "米米号后台详情任务失败",
                exc_info=(type(error), error, error.__traceback__),
            )


class PlayerService:
    def __init__(
        self,
        config: SeerConfig,
        headless: HeadlessService,
        bindings: PlayerBindingStore,
        error_message: ErrorMessageLookup,
        details: PlayerDetailService,
    ) -> None:
        self._config = config
        self._headless = headless
        self._bindings = bindings
        self._error_message = error_message
        self._details = details

    def default_player_id(self, qq_user_id: int) -> int | None:
        return self._bindings.get(qq_user_id).player_id

    async def query(
        self,
        player_id: int,
        *,
        qq_user_id: int,
        explicit: bool,
    ) -> PlayerQueryResult:
        result = await self._query(player_id, source="米米号查询")
        if result.pending is None:
            return result
        binding = self._bindings.get(qq_user_id)
        return PlayerQueryResult(
            pending=result.pending,
            offer_binding=explicit and not binding.choice_completed,
        )

    async def bind_player(
        self,
        qq_user_id: int,
        player_id: int,
    ) -> PlayerQueryResult:
        result = await self._query(player_id, source="米米号绑定")
        pending = result.pending
        if pending is None:
            return result
        status = self._save_binding(qq_user_id, pending)
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return PlayerQueryResult(pending=pending)

    def save_binding_choice(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
        *,
        accepted: bool,
    ) -> str:
        if accepted:
            status = self._save_binding(qq_user_id, pending)
        else:
            try:
                self._bindings.decline(qq_user_id=qq_user_id)
                status = "已跳过默认米米号设置。"
            except Exception as error:
                logger.exception("保存米米号绑定选择失败")
                status = f"⚠️ 默认米米号设置保存失败：{error}"
        pending.player_message = f"{status}\n\n{pending.player_message}"
        return status

    def binding_offer(self, pending: PendingPlayerQuery) -> str:
        return player_binding_offer_message(
            pending.player_id,
            str(pending.user_info.nick),
        )

    def unbind(self, qq_user_id: int) -> str:
        removed = self._bindings.unbind(qq_user_id=qq_user_id)
        return "已解除默认米米号。" if removed else "当前没有已绑定的米米号。"

    def create_detail_task(
        self,
        pending: PendingPlayerQuery,
    ) -> asyncio.Task[PlayerDetailMessages] | None:
        return self._details.create_task(pending)

    def spawn_task(
        self,
        coroutine: Coroutine[Any, Any, T],
        *,
        name: str,
    ) -> asyncio.Task[T]:
        return self._details.spawn_task(coroutine, name=name)

    async def shortcut(
        self,
        command: PlayerShortcutCommand,
        qq_user_id: int,
    ) -> str:
        player_id = command.player_id or self.default_player_id(qq_user_id)
        if player_id is None:
            return (
                "尚未设置默认米米号，请发送“米米号+数字”查询，"
                "或直接在本指令后填写米米号。"
            )
        try:
            game = self._headless.get_game()
            with game.operations.track(
                "米米号快捷详情查询",
                f"米米号 {player_id}",
                source="米米号快捷详情查询",
            ):
                message = await asyncio.wait_for(
                    self._details.shortcut(game, command, player_id),
                    timeout=self._config.player.detail_timeout_seconds,
                )
            await self._headless.mark_available(
                source="米米号快捷详情查询",
                user_id=int(game.user_id),
            )
        except TimeoutError:
            return player_query_timeout_message(player_id)
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            return self.format_error(player_id, error)
        except Exception as error:  # noqa: BLE001
            return player_query_failure_message(player_id, error)
        return message

    def format_error(
        self,
        player_id: int,
        error: SocketRecvError | NotLoggedInError | DisconnectedError,
    ) -> str:
        return format_player_query_error(
            player_id,
            error,
            self._error_message,
        )

    async def _query(
        self,
        player_id: int,
        *,
        source: str,
    ) -> PlayerQueryResult:
        try:
            pending = await self._fetch_pending(
                player_id,
                self._headless.get_game(),
            )
            await self._headless.mark_available(
                source=source,
                user_id=int(pending.game.user_id),
            )
            return PlayerQueryResult(pending=pending)
        except TimeoutError:
            return PlayerQueryResult(
                message=player_query_timeout_message(player_id)
            )
        except (SocketRecvError, NotLoggedInError, DisconnectedError) as error:
            if isinstance(error, (NotLoggedInError, DisconnectedError)):
                await self._headless.mark_unavailable(
                    str(error),
                    source=source,
                )
            return PlayerQueryResult(message=self.format_error(player_id, error))
        except Exception as error:  # noqa: BLE001
            return PlayerQueryResult(
                message=player_query_failure_message(player_id, error)
            )

    async def _fetch_pending(
        self,
        player_id: int,
        game: HeadlessGame,
    ) -> PendingPlayerQuery:
        config = self._config
        extra_errors: list[str] = []
        plan = plan_player_query_sections(
            config.player.sections,
            local_rank_enabled=config.local_rank.enabled,
        )
        with game.operations.track(
            "米米号查询",
            f"米米号 {player_id}",
            source="米米号查询",
        ):
            user_info, more_info, online_info = await asyncio.wait_for(
                asyncio.gather(
                    game.get_user_info(player_id),
                    game.get_more_user_info(player_id),
                    optional_player_extra(
                        "在线状态",
                        plan.needs_online_info,
                        lambda: game.get_user_online_info(player_id),
                        None,
                        extra_errors,
                        on_error=PlayerDetailService._log_extra_error,
                    ),
                ),
                timeout=config.player.timeout_seconds,
            )
        team_name = "无"
        if getattr(user_info, "team_id", 0) > 0:
            try:
                team_info = await asyncio.wait_for(
                    game.get_team_info(user_info.team_id),
                    timeout=min(5.0, config.team.timeout_seconds),
                )
                team_name = team_info.name
            except Exception:  # noqa: BLE001
                team_name = str(user_info.team_id)
        player_message = format_compact_player_info(
            user_info,
            more_info,
            team_name=team_name,
            online_info=online_info,
            unity_peak=UnityPeakInfo(),
            peak_rank_summary=PeakSeasonRankSummary.empty(),
            local_summary=LocalRankSummary(),
            has_collection=plan.has_collection,
            has_peak=plan.needs_peak_section,
            has_autocard=plan.has_autocard_rank,
            show_peak=False,
            extra_errors=extra_errors,
        )
        return PendingPlayerQuery(
            player_id=player_id,
            game=game,
            user_info=user_info,
            more_info=more_info,
            player_message=player_message,
            section_plan=plan,
        )

    def _save_binding(
        self,
        qq_user_id: int,
        pending: PendingPlayerQuery,
    ) -> str:
        try:
            self._bindings.bind(
                qq_user_id=qq_user_id,
                player_id=pending.player_id,
                player_nick=str(pending.user_info.nick),
            )
        except Exception as error:
            logger.exception("保存米米号绑定失败")
            return f"⚠️ 默认米米号设置保存失败：{error}"
        return f"已设置默认米米号：{pending.player_id}。"
