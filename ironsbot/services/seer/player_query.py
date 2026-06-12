# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, MutableMapping
    from typing import Any

PLAYER_QUERY_PREFIXES = ("查询玩家信息", "米米号")
PLAYER_COLLECTION_KEY = "_player_collection_message"
PLAYER_PEAK_KEY = "_player_peak_message"
PLAYER_DETAIL_TASK_KEY = "_player_detail_task"
PLAYER_DETAIL_COMMANDS_KEY = "_player_detail_commands"
PLAYER_DETAIL_AUTO_REPLY_KEYS = "_player_detail_auto_reply_keys"
PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY = "_player_detail_auto_reply_tasks"


@dataclass(slots=True)
class PlayerDetailMessages:
    collection_message: str = ""
    peak_message: str = ""


@dataclass(frozen=True, slots=True)
class PlayerQuerySectionPlan:
    show_local_rank: bool
    has_collection: bool
    needs_peak_section: bool
    needs_online_info: bool
    local_rank_enabled: bool

    @property
    def needs_detail_task(self) -> bool:
        return (
            self.has_collection
            or self.needs_peak_section
            or self.local_rank_enabled
        )


@dataclass(frozen=True, slots=True)
class PlayerDetailFetchPlan:
    needs_unity_part_one: bool
    needs_unity_peak: bool
    needs_rank_summary: bool
    needs_local_rank: bool


@dataclass(frozen=True, slots=True)
class PlayerDetailReplyRequest:
    key: str
    label: str


@dataclass(frozen=True, slots=True)
class PlayerPeakScores:
    standard: int | None = None
    wild: int | None = None
    expert: int | None = None


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


def build_peak_rating_score(rank: int, star: int) -> int | None:
    if rank <= 0 and star <= 0:
        return None
    return rank * 100000 + star


def resolve_player_detail_reply(text_value: str) -> PlayerDetailReplyRequest | None:
    normalized = _normalize_detail_command_text(text_value)
    if normalized == "收集":
        return PlayerDetailReplyRequest(
            key=PLAYER_COLLECTION_KEY,
            label="收集与排行",
        )
    if normalized == "巅峰":
        return PlayerDetailReplyRequest(
            key=PLAYER_PEAK_KEY,
            label="巅峰之战",
        )
    return None


def store_player_detail_messages(
    state: MutableMapping[str, Any],
    detail_messages: PlayerDetailMessages,
) -> None:
    state[PLAYER_COLLECTION_KEY] = detail_messages.collection_message
    state[PLAYER_PEAK_KEY] = detail_messages.peak_message


def cached_player_detail_message(
    state: MutableMapping[str, Any],
    key: str,
) -> str:
    return str(state.get(key) or "")


def player_detail_auto_reply_keys(state: MutableMapping[str, Any]) -> set[str]:
    raw_keys = state.get(PLAYER_DETAIL_AUTO_REPLY_KEYS)
    if isinstance(raw_keys, set):
        return raw_keys

    keys: set[str] = set()
    state[PLAYER_DETAIL_AUTO_REPLY_KEYS] = keys
    return keys


def player_detail_auto_reply_tasks(state: MutableMapping[str, Any]) -> set[Any]:
    raw_tasks = state.get(PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY)
    if isinstance(raw_tasks, set):
        return raw_tasks

    tasks: set[Any] = set()
    state[PLAYER_DETAIL_AUTO_REPLY_TASKS_KEY] = tasks
    return tasks


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
        needs_online_info="basic" in enabled_sections,
        local_rank_enabled=local_rank_enabled,
    )


def plan_player_detail_fetches(
    *,
    has_collection: bool,
    needs_peak_section: bool,
    local_rank_enabled: bool,
) -> PlayerDetailFetchPlan:
    needs_unity_part_one = has_collection
    needs_unity_peak = needs_peak_section
    needs_rank_summary = has_collection or local_rank_enabled

    if local_rank_enabled:
        needs_unity_part_one = True
        needs_unity_peak = True

    return PlayerDetailFetchPlan(
        needs_unity_part_one=needs_unity_part_one,
        needs_unity_peak=needs_unity_peak,
        needs_rank_summary=needs_rank_summary,
        needs_local_rank=local_rank_enabled,
    )


def player_detail_commands(
    *,
    has_collection: bool,
    has_peak: bool,
) -> tuple[str, ...]:
    commands: list[str] = []
    if has_collection:
        commands.append("收集")
    if has_peak:
        commands.append("巅峰")
    return tuple(commands)


def player_query_in_progress_message(player_id: int) -> str:
    return (
        f"⏳ 正在查询米米号 {player_id}，请等当前查询完成。\n"
        "米米号查询需要连接游戏服务器；收集、巅峰和全服排行数据会更慢，"
        "排名越靠后可能查得越久，多人同时查询时也可能需要排队。"
    )


def player_query_timeout_message(player_id: int) -> str:
    return f"❌ 米米号 {player_id} 查询超时，请稍后再试。"


def player_query_failure_message(player_id: int, error: object) -> str:
    return f"❌ 米米号 {player_id} 查询失败：{error}"


def player_query_wait_message(remaining: int) -> str:
    return (
        f"⏳ 刚刚已经发起过米米号查询，请 {remaining} 秒后再试。\n"
        "收集、巅峰和全服排行数据会更慢，排名越靠后可能查得越久，"
        "多人同时查询时也可能需要排队。"
    )


def player_detail_timeout_message(label: str) -> str:
    return f"❌ {label}数据查询超时，请稍后再试。"


def player_detail_failure_message(label: str, error: object) -> str:
    return f"❌ {label}数据获取失败：{error}"


def player_detail_empty_message(label: str) -> str:
    return f"❌ {label}数据没有返回结果，请稍后再试。"


def player_detail_pending_message(label: str) -> str:
    return (
        f"⏳ {label}还在查询中，请稍等后再试。\n"
        "这部分需要拉取收集、全服榜或赛季榜数据，排名越靠后可能越慢，"
        "多人同时查询时也可能需要排队。"
    )


def _normalize_detail_command_text(text_value: str) -> str:
    return "".join(text_value.split()).lower()
