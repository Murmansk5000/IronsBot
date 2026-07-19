# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re

from ironsbot.core.commands import normalize_command_text, strip_command_prefix
from ironsbot.services.seer.rank_list_models import (
    BATCH_CACHE_PREFIXES,
    GLOBAL_RANKS,
    LOCAL_RANKS,
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

MAX_PLAYER_ID = 2_000_000_000



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


def parse_rank_player_command(text: str) -> RankPlayerCommand | None:
    command = normalize_command_text(text)
    parsed = _match_rank_list_command(command)
    if parsed is None:
        return None

    kind, rank_key, suffix = parsed
    if kind != "global" or re.fullmatch(r"\d+", suffix) is None:
        return None

    player_id = int(suffix)
    if not 0 < player_id <= MAX_PLAYER_ID:
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


def _build_command_map() -> dict[str, tuple[str, str]]:
    commands: dict[str, tuple[str, str]] = {}

    aliases = {
        "图鉴积分": ("图鉴积分榜", "图鉴榜"),
        "成就点数": ("成就点数榜", "成就榜"),
        "精灵图鉴": ("精灵图鉴榜", "精灵种类榜", "精灵榜"),
        "皮肤图鉴": ("皮肤图鉴榜", "皮肤榜"),
        "套装图鉴": ("套装图鉴榜", "套装榜"),
        "部件图鉴": ("部件图鉴榜", "部件榜"),
        "座驾图鉴": ("座驾图鉴榜", "座驾榜"),
        "刻印图鉴": ("刻印图鉴榜", "刻印榜"),
        "群星牌": (
            "群星牌榜",
            "群星之巅榜",
            "群星榜",
            "群星百强榜",
            "群星牌百强榜",
        ),
        "竞技段位": ("竞技段位榜", "竞技榜"),
        "狂野段位": ("狂野段位榜", "狂野榜"),
        "专家段位": ("专家段位榜", "专家榜"),
    }
    for key, names in aliases.items():
        for name in names:
            commands[name] = ("global", key)

    local_aliases = {
        "精灵数量": (
            "精灵总数榜",
            "样本精灵数量榜",
            "样本精灵总数榜",
            "样品精灵数量榜",
            "样品精灵总数榜",
            "机器人精灵数量榜",
            "机器人精灵总数榜",
        ),
        "精灵图鉴": ("样本精灵榜", "机器人精灵榜"),
        "群星牌": ("样本群星牌积分榜", "机器人群星牌积分榜"),
        "已解锁图鉴": ("样本已解锁图鉴榜", "机器人已解锁图鉴榜", "解锁图鉴榜"),
        "成就数量": ("样本成就数量榜", "机器人成就数量榜"),
        "竞技段位": ("样本竞技段位榜", "机器人竞技段位榜", "样本竞技榜"),
        "竞技胜率": ("样本竞技胜率榜", "机器人竞技胜率榜"),
        "竞技场次": ("样本竞技场次榜", "机器人竞技场次榜", "竞技场次榜"),
        "狂野段位": ("样本狂野段位榜", "机器人狂野段位榜", "样本狂野榜"),
        "狂野胜率": ("样本狂野胜率榜", "机器人狂野胜率榜"),
        "狂野场次": ("样本狂野场次榜", "机器人狂野场次榜", "狂野场次榜"),
        "专家段位": ("样本专家段位榜", "机器人专家段位榜", "样本专家榜"),
        "专家胜率": ("样本专家胜率榜", "机器人专家胜率榜"),
        "专家场次": ("样本专家场次榜", "机器人专家场次榜", "专家场次榜"),
        "巅峰总场次": (
            "样本场次榜",
            "样本场次总榜",
            "样本总场次榜",
            "样本巅峰场次榜",
            "样本巅峰总场次榜",
            "机器人场次榜",
            "机器人场次总榜",
            "机器人总场次榜",
            "场次榜",
            "场次总榜",
            "总场次榜",
        ),
    }
    for key, spec in GLOBAL_RANKS.items():
        if key not in LOCAL_RANKS:
            continue
        names = (
            f"样本{key}榜",
            f"机器人{key}榜",
            f"样本{spec.title}",
            f"机器人{spec.title}",
            *(f"样本{name}" for name in aliases.get(key, ())),
            *(f"机器人{name}" for name in aliases.get(key, ())),
        )
        local_aliases[key] = (*local_aliases.get(key, ()), *names)

    for key, names in local_aliases.items():
        for name in names:
            commands[name] = ("local", key)

    return commands


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


_COMMANDS = _build_command_map()
_NORMALIZED_COMMANDS = {
    normalize_command_text(command): value for command, value in _COMMANDS.items()
}
