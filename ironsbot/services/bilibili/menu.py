from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from ironsbot.services.bilibili.cache import DynamicHistoryRecord

DYNAMIC_IDS_STATE_KEY = "_bilibili_dynamic_ids"

DynamicSelectionStatus = Literal["ok", "expired", "invalid", "out_of_range"]


@dataclass(frozen=True, slots=True)
class DynamicSelection:
    status: DynamicSelectionStatus
    dynamic_id: str = ""
    available_count: int = 0

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


def build_dynamic_menu_text(records: Sequence[DynamicHistoryRecord]) -> str:
    lines = [
        "📋 【最新动态列表】",
        "👉 发送数字查看详情",
        "-------------------------",
    ]

    for index, record in enumerate(records, start=1):
        time_str = (
            datetime.fromtimestamp(record.pub_ts, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        suppressed_tag = "（未推送）" if record.suppressed else ""
        lines.extend(
            [
                f"【{index}】 ⏰ {time_str}{suppressed_tag}",
                f"👤 {record.author_name}（UID：{record.uid}）",
                f"📝 {record.brief}",
            ]
        )

    lines.extend(
        [
            "-------------------------",
            "💡 两分钟内有效",
        ]
    )
    return "\n".join(lines)


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
