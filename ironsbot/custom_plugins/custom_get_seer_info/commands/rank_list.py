# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from nonebot.adapters import Event
from nonebot.matcher import Matcher

from ironsbot.utils.rule import no_reply

from ..group import matcher_group
from ._client import get_game_client
from ._local_rank import get_local_rank_entries
from ._rank import (
    ACHIEVE_RANK_KEY,
    ACHIEVE_RANK_SUB_KEY,
    BOOK_RANK_KEY,
    BOOK_RANK_SUB_KEY,
    COUNTERMARK_RANK_KEY,
    COUNTERMARK_RANK_SUB_KEY,
    MOUNT_RANK_SUB_KEY,
    OUTFIT_PART_RANK_SUB_KEY,
    OUTFIT_RANK_KEY,
    OUTFIT_SUIT_RANK_SUB_KEY,
    PET_KIND_RANK_ANOMALY_COUNT,
    PET_KIND_RANK_KEY,
    PET_KIND_RANK_SUB_KEY,
    SKIN_RANK_KEY,
    SKIN_RANK_SUB_KEY,
    fetch_daily_rank_page,
    get_current_peak_sub_key,
)

RANK_LIST_SIZE = 20


@dataclass(frozen=True, slots=True)
class GlobalRankSpec:
    title: str
    key: int
    sub_key: int
    unit: str
    start: int = 0
    rank_offset: int = 0


@dataclass(frozen=True, slots=True)
class LocalRankSpec:
    title: str
    metric_key: str
    season_limited: bool = False


GLOBAL_RANKS: dict[str, GlobalRankSpec] = {
    "图鉴积分": GlobalRankSpec("图鉴积分榜", BOOK_RANK_KEY, BOOK_RANK_SUB_KEY, "分"),
    "成就点数": GlobalRankSpec(
        "成就点数榜", ACHIEVE_RANK_KEY, ACHIEVE_RANK_SUB_KEY, "点"
    ),
    "精灵图鉴": GlobalRankSpec(
        "精灵图鉴榜",
        PET_KIND_RANK_KEY,
        PET_KIND_RANK_SUB_KEY,
        "项",
        start=PET_KIND_RANK_ANOMALY_COUNT,
        rank_offset=-PET_KIND_RANK_ANOMALY_COUNT,
    ),
    "皮肤图鉴": GlobalRankSpec("皮肤图鉴榜", SKIN_RANK_KEY, SKIN_RANK_SUB_KEY, "款"),
    "套装图鉴": GlobalRankSpec(
        "套装图鉴榜", OUTFIT_RANK_KEY, OUTFIT_SUIT_RANK_SUB_KEY, "套"
    ),
    "部件图鉴": GlobalRankSpec(
        "部件图鉴榜", OUTFIT_RANK_KEY, OUTFIT_PART_RANK_SUB_KEY, "件"
    ),
    "座驾图鉴": GlobalRankSpec("座驾图鉴榜", OUTFIT_RANK_KEY, MOUNT_RANK_SUB_KEY, "个"),
    "刻印图鉴": GlobalRankSpec(
        "刻印图鉴榜", COUNTERMARK_RANK_KEY, COUNTERMARK_RANK_SUB_KEY, "枚"
    ),
}

LOCAL_RANKS: dict[str, LocalRankSpec] = {
    "图鉴积分": LocalRankSpec("样本图鉴积分榜", "book_score"),
    "成就点数": LocalRankSpec("样本成就点数榜", "achievement_score"),
    "精灵数量": LocalRankSpec("样本精灵总数榜", "pet_total_count"),
    "精灵图鉴": LocalRankSpec("样本精灵图鉴榜", "pet_kind_count"),
    "皮肤图鉴": LocalRankSpec("样本皮肤图鉴榜", "skin_count"),
    "套装图鉴": LocalRankSpec("样本套装图鉴榜", "outfit_suit_count"),
    "部件图鉴": LocalRankSpec("样本部件图鉴榜", "outfit_part_count"),
    "座驾图鉴": LocalRankSpec("样本座驾图鉴榜", "mount_count"),
    "刻印图鉴": LocalRankSpec("样本刻印图鉴榜", "countermark_count"),
    "已解锁图鉴": LocalRankSpec("样本已解锁图鉴榜", "unlocked_book_entries"),
    "成就数量": LocalRankSpec("样本成就数量榜", "achievement_count"),
    "竞技段位": LocalRankSpec(
        "样本竞技段位榜", "peak_standard", season_limited=True
    ),
    "竞技胜率": LocalRankSpec(
        "样本竞技胜率榜", "peak_standard_win_rate", season_limited=True
    ),
    "狂野段位": LocalRankSpec("样本狂野段位榜", "peak_wild", season_limited=True),
    "狂野胜率": LocalRankSpec(
        "样本狂野胜率榜", "peak_wild_win_rate", season_limited=True
    ),
    "专家段位": LocalRankSpec("样本专家段位榜", "peak_expert", season_limited=True),
    "专家胜率": LocalRankSpec(
        "样本专家胜率榜", "peak_expert_win_rate", season_limited=True
    ),
}


def _build_command_map() -> dict[str, tuple[str, str]]:
    commands: dict[str, tuple[str, str]] = {}

    aliases = {
        "图鉴积分": ("图鉴积分榜", "图鉴榜"),
        "成就点数": ("成就点数榜", "成就榜"),
        "精灵图鉴": ("精灵图鉴榜", "精灵种类榜"),
        "皮肤图鉴": ("皮肤图鉴榜", "皮肤榜"),
        "套装图鉴": ("套装图鉴榜", "套装榜"),
        "部件图鉴": ("部件图鉴榜", "部件榜"),
        "座驾图鉴": ("座驾图鉴榜", "座驾榜"),
        "刻印图鉴": ("刻印图鉴榜", "刻印榜"),
    }
    for key, names in aliases.items():
        for name in names:
            commands[name] = ("global", key)

    local_aliases = {
        "精灵数量": ("精灵总数榜", "样本精灵总数榜", "机器人精灵总数榜"),
        "已解锁图鉴": ("样本已解锁图鉴榜", "机器人已解锁图鉴榜", "解锁图鉴榜"),
        "成就数量": ("样本成就数量榜", "机器人成就数量榜"),
        "竞技段位": ("样本竞技段位榜", "机器人竞技段位榜", "样本竞技榜"),
        "竞技胜率": ("样本竞技胜率榜", "机器人竞技胜率榜"),
        "狂野段位": ("样本狂野段位榜", "机器人狂野段位榜", "样本狂野榜"),
        "狂野胜率": ("样本狂野胜率榜", "机器人狂野胜率榜"),
        "专家段位": ("样本专家段位榜", "机器人专家段位榜", "样本专家榜"),
        "专家胜率": ("样本专家胜率榜", "机器人专家胜率榜"),
    }
    for key, spec in GLOBAL_RANKS.items():
        names = (
            f"样本{key}榜",
            f"机器人{key}榜",
            f"样本{spec.title}",
            f"机器人{spec.title}",
            *(f"样本{name}" for name in aliases.get(key, ())),
            *(f"机器人{name}" for name in aliases.get(key, ())),
        )
        local_aliases.setdefault(key, names)

    for key, names in local_aliases.items():
        for name in names:
            commands[name] = ("local", key)

    return commands


COMMANDS = _build_command_map()

rank_list_matcher = matcher_group.on_fullmatch(tuple(COMMANDS), rule=no_reply())


def _now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _format_global_line(
    item: Any,
    *,
    index: int,
    spec: GlobalRankSpec,
) -> str:
    rank = index + 1 + spec.rank_offset
    return f"{rank}. {item.nick}（{item.id}） {item.score}{spec.unit}"


async def _build_global_rank_message(spec: GlobalRankSpec) -> str:
    game = get_game_client()
    items = await fetch_daily_rank_page(
        game,
        key=spec.key,
        sub_key=spec.sub_key,
        start=spec.start,
        count=RANK_LIST_SIZE,
    )
    if not items:
        return f"❌找不到{spec.title}数据。"

    lines = [f"{spec.title}（截至{_now_text()}）"]
    lines.extend(
        _format_global_line(item, index=spec.start + index, spec=spec)
        for index, item in enumerate(items)
    )
    return "\n".join(lines)


def _build_local_rank_message(spec: LocalRankSpec) -> str:
    season_sub_key = get_current_peak_sub_key() if spec.season_limited else None
    entries, sample_count = get_local_rank_entries(
        spec.metric_key,
        limit=RANK_LIST_SIZE,
        season_sub_key=season_sub_key,
    )
    if not entries:
        return f"❌暂无{spec.title}数据。先查询一些米米号后再试。"

    title = f"{spec.title}（样本{sample_count}人，截至{_now_text()}）"
    if season_sub_key is not None:
        title += f"\n赛季样本：{season_sub_key}"

    lines = [title]
    lines.extend(
        f"{entry.rank}. {entry.nick}（{entry.user_id}） {entry.display}"
        for entry in entries
    )
    return "\n".join(lines)


@rank_list_matcher.handle()
async def handle_rank_list(matcher: Matcher, event: Event) -> None:
    command = event.get_plaintext().strip()
    kind, key = COMMANDS[command]

    if kind == "global":
        await matcher.finish(await _build_global_rank_message(GLOBAL_RANKS[key]))

    await matcher.finish(_build_local_rank_message(LOCAL_RANKS[key]))
