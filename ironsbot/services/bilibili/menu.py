from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from ironsbot.core.selection import SelectionMenuItem, format_selection_menu

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.services.bilibili.dynamic_history import DynamicHistoryRecord

DYNAMIC_MENU_DEFAULT_LIMIT = 10

DynamicMenuStatus = Literal[
    "ok",
    "no_accounts",
    "auth_invalid",
    "no_history",
]


@dataclass(frozen=True, slots=True)
class DynamicMenuResult:
    status: DynamicMenuStatus
    dynamic_ids: tuple[str, ...] = ()
    prompt: str = ""


def build_dynamic_menu_text(records: Sequence[DynamicHistoryRecord]) -> str:
    items: list[SelectionMenuItem] = []

    for record in records:
        time_str = (
            datetime.fromtimestamp(record.pub_ts, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        suppressed_tag = "（未推送）" if record.suppressed else ""
        items.append(
            SelectionMenuItem(
                label=f"⏰ {time_str}{suppressed_tag}",
                detail_lines=(
                    f"👤 {record.author_name}（UID：{record.uid}）",
                    f"📝 {record.brief}",
                ),
            )
        )

    return format_selection_menu(
        title="📋 【最新动态列表】",
        intro_lines=("👉 发送数字查看详情", "-------------------------"),
        items=tuple(items),
        footer=None,
    )


def dynamic_record_ids(records: Sequence[DynamicHistoryRecord]) -> list[str]:
    return [record.dynamic_id for record in records]
