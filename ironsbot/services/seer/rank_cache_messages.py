# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.services.seer.rank_list_models import RANK_LIST_SIZE, GlobalRankSpec

if TYPE_CHECKING:
    from ironsbot.services.seer.local_rank_models import LocalRankCacheStats
    from ironsbot.services.seer.local_rank_refresh import LocalRankRefreshResult
    from ironsbot.services.seer.rank_list_models import RankCacheBatchCommand

_FAILURE_PREVIEW_LIMIT = 5


def build_rank_batch_no_players_message(spec: GlobalRankSpec) -> str:
    return f"❌ 没有从{spec.title}拿到可缓存的榜单数据。"


def build_rank_batch_start_message(
    spec: GlobalRankSpec,
    command: RankCacheBatchCommand,
    *,
    item_count: int,
    requested_count: int,
) -> str:
    truncated_text = ""
    if requested_count > item_count:
        truncated_text = (
            "\n本次按 seer.local_rank.batch_limit "
            f"只处理前 {item_count} 个。"
        )

    return (
        f"🔄 正在缓存{spec.title}第 {command.start_rank}-{command.end_rank} 名。"
        f"\n实际拿到 {item_count} 条榜单数据。"
        "\n只写入全服榜单页缓存，不计入样本。"
        f"{truncated_text}"
    )


def build_rank_batch_result_message(
    spec: GlobalRankSpec,
    command: RankCacheBatchCommand,
    *,
    item_count: int,
    requested_count: int,
) -> str:
    truncated_text = ""
    if requested_count > item_count:
        truncated_text = f"\n本次实际缓存：{item_count}/{requested_count} 条"

    lines = [
        "✅【榜单区间缓存完成】",
        f"榜单：{spec.title}",
        f"请求区间：第 {command.start_rank}-{command.end_rank} 名",
        f"写入榜单页缓存：{item_count} 条",
        "样本缓存：未写入",
    ]
    if truncated_text:
        lines.append(truncated_text.strip())
    return "\n".join(lines)


def build_local_rank_cache_status_message(  # noqa: PLR0913
    stats: LocalRankCacheStats,
    *,
    rank_limit: int,
    batch_limit: int,
    refresh_limit: int,
    refresh_max_age_hours: int,
    display_limit: int = RANK_LIST_SIZE,
) -> str:
    lines = [
        "📊【样本榜缓存状态】",
        f"已缓存米米号：{stats.player_count}/{stats.max_players} 个",
        f"总缓存玩家：{stats.total_player_count} 个"
        "（含全服榜单扫到但未计入样本的人）",
        f"全服排行扫描上限：前 {rank_limit} 名",
        f"单次批量缓存上限：{batch_limit} 个",
        f"单轮刷新上限：{refresh_limit} 个",
        f"刷新过期时间：{refresh_max_age_hours} 小时",
        "巅峰样本：按当前赛季单独比较",
        f"榜单命令展示：前 {display_limit} 名",
        "",
        "可参与排行人数：",
    ]
    lines.extend(
        f"{title}：{count}"
        for title, count in stats.metric_counts.items()
    )
    return "\n".join(lines)


def build_local_rank_refresh_empty_message() -> str:
    return "❌ 当前没有本地样本缓存。先查询一些米米号后再刷新。"


def build_local_rank_refresh_start_message(
    before_stats: LocalRankCacheStats,
    *,
    refresh_limit: int,
    refresh_max_age_hours: int,
) -> str:
    return (
        "🔄 正在刷新样本榜缓存。"
        f"样本共 {before_stats.player_count} 个，本轮按最旧优先最多刷新 "
        f"{refresh_limit} 个，"
        "只刷新超过 "
        f"{refresh_max_age_hours} "
        "小时未更新的数据。"
    )


def build_local_rank_refresh_result_message(
    result: LocalRankRefreshResult,
    after_stats: LocalRankCacheStats,
) -> str:
    lines = [
        "✅【样本榜缓存刷新完成】",
        f"本轮候选米米号：{result.total} 个",
        f"成功刷新：{result.success} 个",
        f"缓存已满跳过：{result.skipped_full} 个",
        f"失败：{result.failed} 个",
        f"当前缓存米米号：{after_stats.player_count}/{after_stats.max_players} 个",
    ]
    failures = result.failures[:_FAILURE_PREVIEW_LIMIT]
    if failures:
        lines.append("")
        lines.append("失败示例：")
        lines.extend(
            f"- {failure.player_id}: {failure.reason}" for failure in failures
        )
        if result.failed > _FAILURE_PREVIEW_LIMIT:
            lines.append(
                f"- 另有 {result.failed - _FAILURE_PREVIEW_LIMIT} 个失败，"
                "日志里可继续看。"
            )
    return "\n".join(lines)
