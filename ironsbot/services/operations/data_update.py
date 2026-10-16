# SPDX-License-Identifier: MIT
"""Platform-independent, durable-data update events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ironsbot.core.time import TZ_CN

_OFFICIAL_VERSION_LENGTH = 14


@dataclass(frozen=True, slots=True)
class DataVersion:
    version: str
    season: tuple[datetime, datetime] | None = None
    generated_at: datetime | None = None
    official_version: str | None = None


def valid_official_version(value: str | None) -> bool:
    if (
        value is None
        or len(value) != _OFFICIAL_VERSION_LENGTH
        or not value.isascii()
        or not value.isdecimal()
    ):
        return False
    try:
        datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=TZ_CN)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class DataUpdate:
    source: str
    before: DataVersion
    after: DataVersion
    completed_at: datetime

    def message(self) -> str:
        generated_at = self.after.generated_at
        timestamp = (
            f"{generated_at.astimezone(TZ_CN):%Y-%m-%d %H:%M:%S}（北京时间）"
            if generated_at is not None and generated_at.tzinfo is not None
            else "未知"
        )
        if self.source == "seerapi":
            return (
                "📢游戏配置已更新，可查询最新数据\n"
                f"官方配置版本：{self.before.official_version}"
                f" → {self.after.official_version}\n"
                f"数据生成时间：{timestamp}"
            )
        return f"📢别名数据已更新，可查询最新数据\n数据时间：{timestamp}"
