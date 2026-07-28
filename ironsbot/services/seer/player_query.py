# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ironsbot.core.selection import (
    EXIT_SELECTION_LINE,
)
from ironsbot.services.seer.rank_peak import build_peak_rating_score

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, MutableMapping
    from typing import Any

    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionAction,
    )
    from ironsbot.services.seer.rank_models import PeakSeasonRankSummary
    from ironsbot.services.seer.sequ_extra import UnityPeakInfo

PLAYER_QUERY_PREFIXES = ("查询玩家信息", "米米号")
PLAYER_COLLECTION_KEY = "_player_collection_message"
PLAYER_PEAK_KEY = "_player_peak_message"
PLAYER_AUTOCARD_KEY = "_player_autocard_message"
PLAYER_DETAIL_COMMANDS_KEY = "_player_detail_commands"
PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY = "_player_detail_builtin_selections"
PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY = "_player_detail_extension_selections"


@dataclass(frozen=True, slots=True)
class PlayerQuerySectionPlan:
    show_local_rank: bool
    has_collection: bool
    needs_peak_section: bool
    has_autocard_rank: bool
    needs_online_info: bool
    local_rank_enabled: bool


@dataclass(frozen=True, slots=True)
class PlayerDetailReplyRequest:
    key: str
    label: str
    menu_label: str


_PLAYER_DETAIL_REQUESTS = (
    PlayerDetailReplyRequest(
        key=PLAYER_COLLECTION_KEY,
        label="收集与排行",
        menu_label="收集",
    ),
    PlayerDetailReplyRequest(
        key=PLAYER_PEAK_KEY,
        label="巅峰之战",
        menu_label="巅峰",
    ),
    PlayerDetailReplyRequest(
        key=PLAYER_AUTOCARD_KEY,
        label="群星牌排名",
        menu_label="群星牌",
    ),
)
_PLAYER_DETAIL_REQUEST_BY_KEY = {
    request.key: request for request in _PLAYER_DETAIL_REQUESTS
}


@dataclass(frozen=True, slots=True)
class PlayerDetailPromptPlan:
    accepted_commands: tuple[str, ...]
    prompt_lines: tuple[str, ...]
    builtin_selections: tuple[tuple[str, str], ...]
    extension_selections: tuple[tuple[str, str], ...]
    should_enter_conversation: bool


@dataclass(frozen=True, slots=True)
class PlayerPeakScores:
    standard: int | None = None
    wild: int | None = None
    expert: int | None = None


@dataclass(frozen=True, slots=True)
class ValidatedPlayerPeak:
    unity_peak: UnityPeakInfo
    scores: PlayerPeakScores
    clear_metric_keys: frozenset[str] = frozenset()


def extract_player_query_arg(text_value: str) -> str | None:
    stripped = text_value.strip()
    folded = stripped.casefold()
    for prefix in PLAYER_QUERY_PREFIXES:
        if folded.startswith(prefix.casefold()):
            return stripped[len(prefix) :].strip()
    return None


def calculate_player_peak_scores(unity_peak: object) -> PlayerPeakScores:
    standard_score = (
        build_peak_rating_score(
            int(getattr(unity_peak, "current_j_rank", 0)),
            int(getattr(unity_peak, "current_j_star", 0)),
        )
        if int(getattr(unity_peak, "current_j_all", 0)) > 0
        else None
    )
    wild_score = (
        build_peak_rating_score(
            int(getattr(unity_peak, "current_k_rank", 0)),
            int(getattr(unity_peak, "current_k_star", 0)),
        )
        if int(getattr(unity_peak, "current_k_all", 0)) > 0
        else None
    )
    expert_score = (
        int(getattr(unity_peak, "current_z_score", 0))
        if int(getattr(unity_peak, "current_z_all", 0)) > 0
        else None
    )
    return PlayerPeakScores(
        standard=standard_score,
        wild=wild_score,
        expert=expert_score,
    )


def validate_player_peak_season(
    unity_peak: UnityPeakInfo,
    candidate_scores: PlayerPeakScores,
    rank_summary: PeakSeasonRankSummary,
) -> ValidatedPlayerPeak:
    scores: dict[str, int | None] = {}
    peak_updates: dict[str, int] = {}
    clear_metric_keys: set[str] = set()
    invalidates_total_matches = False
    mode_specs = (
        (
            "standard",
            candidate_scores.standard,
            rank_summary.standard,
            "current_j_win",
            "current_j_all",
            (
                "peak_standard",
                "peak_standard_win_rate",
                "peak_standard_matches",
            ),
        ),
        (
            "wild",
            candidate_scores.wild,
            rank_summary.wild,
            "current_k_win",
            "current_k_all",
            ("peak_wild", "peak_wild_win_rate", "peak_wild_matches"),
        ),
        (
            "expert",
            candidate_scores.expert,
            rank_summary.expert,
            "current_z_win",
            "current_z_all",
            ("peak_expert", "peak_expert_win_rate", "peak_expert_matches"),
        ),
    )
    for (
        mode,
        candidate_score,
        result,
        win_field,
        total_field,
        metric_keys,
    ) in mode_specs:
        confirmed_score = (
            int(result.score)
            if result.rank is not None and result.score is not None
            else None
        )
        # A rank lookup that did not find the player (or timed out) does not
        # prove that the live player packet belongs to an old season.  Keep
        # its match data unless the rank lookup positively returns a different
        # current score.
        scores[mode] = (
            confirmed_score
            if confirmed_score is not None
            else candidate_score
        )
        if confirmed_score is None or confirmed_score == candidate_score:
            continue

        peak_updates[win_field] = 0
        peak_updates[total_field] = 0
        invalidates_total_matches = (
            invalidates_total_matches or int(getattr(unity_peak, total_field)) > 0
        )
        clear_metric_keys.update(metric_keys[1:])

    if invalidates_total_matches:
        clear_metric_keys.add("peak_total_matches")

    return ValidatedPlayerPeak(
        unity_peak=replace(unity_peak, **peak_updates),
        scores=PlayerPeakScores(
            standard=scores["standard"],
            wild=scores["wild"],
            expert=scores["expert"],
        ),
        clear_metric_keys=frozenset(clear_metric_keys),
    )


async def safe_player_extra(  # noqa: PLR0913
    label: str,
    awaitable: Awaitable[Any],
    default: Any,
    extra_errors: list[str] | None,
    *,
    on_error: Callable[[str, Exception], None] | None = None,
    timeout_seconds: float | None = None,
    error_label_factory: Callable[[], str] | None = None,
) -> Any:
    try:
        if timeout_seconds is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except Exception as error:  # noqa: BLE001
        error_label = error_label_factory() if error_label_factory else label
        if on_error is not None:
            on_error(error_label, error)
        if extra_errors is not None:
            extra_errors.append(
                f"{error_label}失败：{format_player_extra_error(error)}"
            )
        return default


async def optional_player_extra(  # noqa: PLR0913
    label: str,
    enabled: bool,  # noqa: FBT001
    awaitable_factory: Callable[[], Awaitable[Any]],
    default: Any,
    extra_errors: list[str] | None,
    *,
    on_error: Callable[[str, Exception], None] | None = None,
    timeout_seconds: float | None = None,
    error_label_factory: Callable[[], str] | None = None,
) -> Any:
    if not enabled:
        return default

    return await safe_player_extra(
        label,
        awaitable_factory(),
        default,
        extra_errors,
        on_error=on_error,
        timeout_seconds=timeout_seconds,
        error_label_factory=error_label_factory,
    )


def format_player_extra_error(error: Exception) -> str:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "查询超时"
    return str(error) or type(error).__name__


def resolve_player_detail_reply(
    text_value: str,
    *,
    selections: Iterable[tuple[str, str]],
) -> PlayerDetailReplyRequest | None:
    normalized = _normalize_detail_command_text(text_value)
    for selection, request_key in selections:
        request = _PLAYER_DETAIL_REQUEST_BY_KEY.get(request_key)
        if request is None:
            continue
        if normalized == selection:
            return request
    return None


def is_player_detail_exit(text_value: str) -> bool:
    return _normalize_detail_command_text(text_value) == "0"


def cached_player_detail_message(
    state: MutableMapping[str, Any],
    key: str,
) -> str:
    return str(state.get(key) or "")


def plan_player_query_sections(
    sections: Iterable[str],
    *,
    local_rank_enabled: bool,
) -> PlayerQuerySectionPlan:
    enabled_sections = set(sections)
    has_collection = bool(
        {"collection", "rank", "local_rank", "achievement"} & enabled_sections
    )
    return PlayerQuerySectionPlan(
        show_local_rank="local_rank" in enabled_sections,
        has_collection=has_collection,
        needs_peak_section="peak" in enabled_sections,
        has_autocard_rank="autocard" in enabled_sections,
        needs_online_info="basic" in enabled_sections,
        local_rank_enabled=local_rank_enabled,
    )


def _available_builtin_detail_requests(
    *,
    has_collection: bool,
    has_peak: bool,
    has_autocard: bool,
) -> tuple[PlayerDetailReplyRequest, ...]:
    requests: list[PlayerDetailReplyRequest] = []
    if has_collection:
        requests.append(_PLAYER_DETAIL_REQUESTS[0])
    if has_peak:
        requests.append(_PLAYER_DETAIL_REQUESTS[1])
    if has_autocard:
        requests.append(_PLAYER_DETAIL_REQUESTS[2])
    return tuple(requests)


def plan_player_detail_prompt(
    *,
    has_collection: bool,
    has_peak: bool,
    has_autocard: bool,
    supports_conversation: bool,
    extension_actions: Iterable[PlayerDetailExtensionAction] = (),
) -> PlayerDetailPromptPlan:
    builtin_requests = _available_builtin_detail_requests(
        has_collection=has_collection,
        has_peak=has_peak,
        has_autocard=has_autocard,
    )
    extensions = tuple(extension_actions)
    builtin_selections = tuple(
        (str(index), request.key)
        for index, request in enumerate(builtin_requests, start=1)
    )
    extension_selections = tuple(
        (str(index), action.id)
        for index, action in enumerate(extensions, start=len(builtin_selections) + 1)
    )
    has_actions = bool(builtin_selections or extension_selections)
    accepted_commands = _unique_commands(
        (
            *(selection for selection, _ in builtin_selections),
            *(selection for selection, _ in extension_selections),
            "0",
        )
        if has_actions
        else ()
    )
    prompt_lines = (
        (
            "回复数字查看详情：",
            *(
                _format_player_detail_menu_item(selection, request.menu_label)
                for selection, request in zip(
                    builtin_selections,
                    builtin_requests,
                    strict=True,
                )
            ),
            *(
                _format_player_detail_menu_item(selection, action.label)
                for selection, action in zip(
                    extension_selections,
                    extensions,
                    strict=True,
                )
            ),
            EXIT_SELECTION_LINE,
        )
        if has_actions
        else ()
    )
    return PlayerDetailPromptPlan(
        accepted_commands=accepted_commands,
        prompt_lines=prompt_lines,
        builtin_selections=builtin_selections,
        extension_selections=extension_selections,
        should_enter_conversation=has_actions and supports_conversation,
    )


def _format_player_detail_menu_item(
    selection: tuple[str, str],
    label: str,
) -> str:
    return f"{selection[0]}.【{label}】"


def _unique_commands(commands: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(commands))


def player_query_timeout_message(player_id: int) -> str:
    return f"❌ 米米号 {player_id} 查询超时，请稍后再试。"


def player_query_failure_message(player_id: int, error: object) -> str:
    detail = str(error).strip()
    if not detail:
        detail = type(error).__name__
    return f"❌ 米米号 {player_id} 查询失败：{detail}"


def _normalize_detail_command_text(text_value: str) -> str:
    return "".join(text_value.split()).lower()
