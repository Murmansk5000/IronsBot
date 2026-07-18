from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from ironsbot.shared.selection_menu import (
    SelectionMenuItem,
    format_selection_menu,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nonebot.adapters.onebot.v11 import Message

    from ironsbot.services.bilibili.dynamic_history import (
        BiliDynamicHistoryStore,
        DynamicHistoryRecord,
    )

DYNAMIC_IDS_STATE_KEY = "_bilibili_dynamic_ids"

DynamicSelectionStatus = Literal["ok", "expired", "invalid", "out_of_range"]
DynamicDetailStatus = Literal[
    "ok",
    "expired",
    "invalid",
    "out_of_range",
    "missing",
    "parse_failed",
]


@dataclass(frozen=True, slots=True)
class DynamicSelection:
    status: DynamicSelectionStatus
    dynamic_id: str = ""
    available_count: int = 0

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True, slots=True)
class DynamicDetailSelection:
    status: DynamicDetailStatus
    message: Message | None = None
    available_count: int = 0

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


def parse_single_item(
    item: dict[str, Any],
    pub_ts: int,
    *,
    menu_mode: bool = False,
    mode: Literal["full", "link"] = "full",
) -> Message | None:
    from ironsbot.services.bilibili.parser import parse_single_item as parse

    return parse(item, pub_ts, menu_mode=menu_mode, mode=mode)


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


def select_cached_dynamic_id(
    cached_ids: Sequence[object],
    raw_text: str,
) -> DynamicSelection:
    if not cached_ids:
        return DynamicSelection(status="expired")

    try:
        select_num = int(raw_text.strip())
    except ValueError:
        return DynamicSelection(
            status="invalid",
            available_count=len(cached_ids),
        )

    if select_num < 1 or select_num > len(cached_ids):
        return DynamicSelection(
            status="out_of_range",
            available_count=len(cached_ids),
        )

    return DynamicSelection(
        status="ok",
        dynamic_id=str(cached_ids[select_num - 1]),
        available_count=len(cached_ids),
    )


def build_dynamic_detail_for_selection(
    history: BiliDynamicHistoryStore,
    cached_ids: Sequence[object],
    raw_text: str,
) -> DynamicDetailSelection:
    selection = select_cached_dynamic_id(cached_ids, raw_text)
    if not selection.is_ok:
        return DynamicDetailSelection(
            status=selection.status,
            available_count=selection.available_count,
        )

    record = history.get(selection.dynamic_id)
    if record is None:
        return DynamicDetailSelection(
            status="missing",
            available_count=selection.available_count,
        )

    message = parse_single_item(
        record.item,
        record.pub_ts,
        menu_mode=True,
        mode="full",
    )
    if message is None:
        return DynamicDetailSelection(
            status="parse_failed",
            available_count=selection.available_count,
        )

    return DynamicDetailSelection(
        status="ok",
        message=message,
        available_count=selection.available_count,
    )
