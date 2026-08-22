# SPDX-License-Identifier: MIT
"""Platform-independent, durable-data update events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ironsbot.core.time import TZ_CN

_OFFICIAL_VERSION_LENGTH = 14


def valid_official_version(value: str) -> bool:
    if (
        len(value) != _OFFICIAL_VERSION_LENGTH
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
class DataVersion:
    version: str
    season: tuple[datetime, datetime] | None = None
    official_version: str = ""


@dataclass(frozen=True, slots=True)
class DataUpdate:
    source: str
    before: DataVersion
    after: DataVersion
    completed_at: datetime

    def message(self) -> str:
        lines = [
            "SeerAPI 数据更新成功",
            f"官方配置版本：{self.before.official_version} → "
            f"{self.after.official_version}",
            f"完成时间：{self.completed_at.astimezone(TZ_CN):%Y-%m-%d %H:%M:%S}",
        ]
        if self.after.season is not None and self.after.season != self.before.season:
            start, end = (value.astimezone(TZ_CN) for value in self.after.season)
            lines.append(
                f"巅峰赛季：{start:%Y%m%d}（{start:%Y-%m-%d %H:%M}"
                f" 至 {end:%Y-%m-%d %H:%M}）"
            )
        return "\n".join(lines)
