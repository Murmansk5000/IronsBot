# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from .rank_list_formatting import now_text as current_time_text

if TYPE_CHECKING:
    from .countermark_stat_rank_models import (
        CountermarkStatRankCommand,
        CountermarkStatRankItem,
        StatSpec,
    )

RANK_LIST_SIZE = 10
AVAILABLE_STATS_TEXT = (
    "攻击 / 防御 / 特攻 / 特防 / 速度 / 体力 / 双防 / 双攻 / 盾 / 双刀 / 总和"
)

def build_countermark_stat_rank_message(
    command: CountermarkStatRankCommand,
    items: list[CountermarkStatRankItem],
    *,
    now_text: str | None = None,
) -> str:
    if command.stat is None:
        return (
            "❌ 刻印数值榜需要指定属性。\n"
            f"可用属性：{AVAILABLE_STATS_TEXT}\n"
            "例：刻印攻击榜 / 六角双攻榜 / 刻印双防体榜 / 特攻双防刻印榜 / 刻印总和榜"
        )

    scope_text = _scope_text(command)
    if not items:
        return (
            f"❌ 没有找到{scope_text}的{command.stat.title}数据。\n"
            "默认已查询全部刻印；如果只想筛选角数，可以发送："
            f"六角刻印{command.stat.title}榜 或 2角刻印{command.stat.title}榜"
        )

    timestamp = current_time_text() if now_text is None else now_text
    lines = [
        f"💮【{scope_text}{command.stat.title}榜】（截至{timestamp}）",
        f"范围：{scope_text} | 展示前 {min(RANK_LIST_SIZE, len(items))} 名",
    ]
    lines.extend(
        _format_item_line(index, item, command.stat)
        for index, item in enumerate(items[:RANK_LIST_SIZE], start=1)
    )
    return "\n".join(lines)


def _scope_text(command: CountermarkStatRankCommand) -> str:
    if command.angle_count is not None:
        return f"{command.angle_count}角刻印"
    return "所有刻印"

def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0")

def _format_item_line(
    index: int,
    item: CountermarkStatRankItem,
    stat: StatSpec,
) -> str:
    class_text = f" | {item.class_name}" if item.class_name else ""
    angle_text = f" | {item.angle_count}角" if item.angle_count else ""
    return (
        f"{index}. {item.mintmark_name}（{item.mintmark_id}）"
        f" {stat.title}{_format_number(item.value)}"
        f" | 总和{_format_number(item.total)}"
        f"{class_text}"
        f"{angle_text}"
    )
