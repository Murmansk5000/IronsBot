# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ironsbot.core.commands import normalize_command_text, strip_command_prefix
from ironsbot.services.seer.ids import is_valid_player_id
from ironsbot.services.seer.rank_catalog import RANK_COMMAND_MAP
from ironsbot.services.seer.rank_list_models import (
    BATCH_CACHE_PREFIXES,
    GLOBAL_RANKS,
    RANK_LIST_MAX_SIZE,
    RANK_LIST_SIZE,
    RANK_PAGE_CACHE_REFRESH_PREFIXES,
    RANK_PAGE_CACHE_STATUS_PREFIXES,
    GlobalRankSpec,
    RankCacheBatchCommand,
    RankListCommand,
    RankPageCacheRefreshCommand,
    RankPageCacheStatusCommand,
    RankPlayerCommand,
    RankScoreCommand,
)
from ironsbot.services.seer.rank_peak import parse_peak_rating_score_text

if TYPE_CHECKING:
    from collections.abc import Callable


def with_admin_prefix(commands: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"/{command}" for command in commands)


def parse_rank_list_command(
    text: str,
    *,
    default_limit: int = RANK_LIST_SIZE,
    max_limit: int = RANK_LIST_MAX_SIZE,
) -> RankListCommand | None:
    command = normalize_command_text(text)
    parsed = _match_rank_list_command(command)
    if parsed is None:
        return None

    kind, rank_key, suffix = parsed
    window = _parse_rank_window(
        suffix,
        default_limit=default_limit,
        max_limit=max_limit,
    )
    if window is None:
        return None

    start_rank, limit = window
    return RankListCommand(
        kind=kind,
        rank_key=rank_key,
        start_rank=start_rank,
        limit=limit,
    )


def parse_rank_score_command(text: str) -> RankScoreCommand | None:
    command = normalize_command_text(text)
    parsed = _match_rank_list_command(command)
    if parsed is None:
        return None

    kind, rank_key, suffix = parsed
    if kind != "global":
        return None

    spec = GLOBAL_RANKS[rank_key]
    unit_pattern = "|".join(
        re.escape(unit)
        for unit in sorted(
            {rank_spec.unit for rank_spec in GLOBAL_RANKS.values()}
            | {spec.unit, "分数", "积分"},
            key=len,
            reverse=True,
        )
    )
    score = _parse_rank_score_suffix(suffix, spec, unit_pattern)
    if score <= 0:
        return None
    return RankScoreCommand(rank_key=rank_key, score=score)


def parse_rank_player_command(
    text: str,
    *,
    resolve_player_id: Callable[[str], int | None] | None = None,
) -> RankPlayerCommand | None:
    command = normalize_command_text(text)
    parsed = _match_rank_list_command(command)
    if parsed is None:
        return None

    kind, rank_key, suffix = parsed
    if kind != "global" or not suffix:
        return None
    if resolve_player_id is not None:
        player_id = resolve_player_id(suffix)
    elif suffix.isdecimal():
        player_id = int(suffix) if is_valid_player_id(int(suffix)) else None
    else:
        player_id = None
    if player_id is None:
        return None
    return RankPlayerCommand(rank_key=rank_key, player_id=player_id)


def parse_rank_cache_batch_command(text: str) -> RankCacheBatchCommand | None:
    stripped = strip_command_prefix(text)
    if stripped is None:
        return None

    command = normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(command, BATCH_CACHE_PREFIXES)
    if normalized_prefix is None:
        return None

    command = command[len(normalized_prefix) :]
    match = re.fullmatch(r"(.+?)(\d+)(?:-|~|到|至)(\d+)", command)
    if match is None:
        return None

    rank_name, start_text, end_text = match.groups()
    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    start_rank = int(start_text)
    end_rank = int(end_text)

    if (
        rank_command is None
        or rank_command[0] != "global"
        or start_rank <= 0
        or end_rank < start_rank
    ):
        return None

    return RankCacheBatchCommand(
        rank_key=rank_command[1],
        start_rank=start_rank,
        end_rank=end_rank,
    )


def parse_rank_page_cache_status_command(
    text: str,
) -> RankPageCacheStatusCommand | None:
    stripped = strip_command_prefix(text)
    if stripped is None:
        return None

    command = normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(
        command,
        RANK_PAGE_CACHE_STATUS_PREFIXES,
    )
    if normalized_prefix is None:
        return None

    rank_name = command[len(normalized_prefix) :]
    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    if rank_command is None or rank_command[0] != "global":
        return None

    return RankPageCacheStatusCommand(rank_key=rank_command[1])


def parse_rank_page_cache_refresh_command(
    text: str,
) -> RankPageCacheRefreshCommand | None:
    stripped = strip_command_prefix(text)
    if stripped is None:
        return None

    command = normalize_command_text(stripped)
    normalized_prefix = _matching_normalized_prefix(
        command,
        RANK_PAGE_CACHE_REFRESH_PREFIXES,
    )
    if normalized_prefix is None:
        return None

    rank_name = command[len(normalized_prefix) :]
    if not rank_name:
        return RankPageCacheRefreshCommand()

    rank_command = _NORMALIZED_COMMANDS.get(rank_name)
    if rank_command is None or rank_command[0] != "global":
        return None

    return RankPageCacheRefreshCommand(rank_key=rank_command[1])


def _parse_rank_score_suffix(
    suffix: str,
    spec: GlobalRankSpec,
    unit_pattern: str,
) -> int:
    if spec.score_format == "peak_rating":
        peak_score = parse_peak_rating_score_text(suffix)
        if peak_score is not None:
            return peak_score

    score_match = re.fullmatch(
        rf"(\d+)(?:{unit_pattern})",
        suffix,
    )
    if score_match is None:
        return 0
    return int(score_match.group(1))


def _match_rank_list_command(command: str) -> tuple[str, str, str] | None:
    for prefix, value in sorted(
        _NORMALIZED_COMMANDS.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if command.startswith(prefix):
            kind, rank_key = value
            return kind, rank_key, command[len(prefix) :]
    return None


def _parse_rank_window(  # noqa: PLR0911
    suffix: str,
    *,
    default_limit: int = RANK_LIST_SIZE,
    max_limit: int = RANK_LIST_MAX_SIZE,
) -> tuple[int, int] | None:
    if not suffix:
        return 1, default_limit

    page_match = re.fullmatch(r"第?(\d+)页", suffix)
    if page_match is not None:
        page = int(page_match.group(1))
        if page <= 0:
            return None
        return (page - 1) * default_limit + 1, default_limit

    range_match = re.fullmatch(r"第?(\d+)(?:-|~|到|至)(\d+)名?", suffix)
    if range_match is not None:
        start_rank = int(range_match.group(1))
        end_rank = int(range_match.group(2))
        if start_rank <= 0 or end_rank < start_rank:
            return None
        return start_rank, min(end_rank - start_rank + 1, max_limit)

    single_match = re.fullmatch(r"第?(\d+)名", suffix)
    if single_match is not None:
        start_rank = int(single_match.group(1))
        if start_rank <= 0:
            return None
        return start_rank, 1

    return None


def _matching_normalized_prefix(
    command: str,
    prefixes: tuple[str, ...],
) -> str | None:
    return next(
        (
            normalized_prefix
            for prefix in prefixes
            if command.startswith(normalized_prefix := normalize_command_text(prefix))
        ),
        None,
    )


_COMMANDS = RANK_COMMAND_MAP
_NORMALIZED_COMMANDS = {
    normalize_command_text(command): value for command, value in _COMMANDS.items()
}
