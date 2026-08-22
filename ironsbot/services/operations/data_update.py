# SPDX-License-Identifier: MIT
"""Platform-independent, durable-data update events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class DataVersion:
    version: str
    season: tuple[datetime, datetime] | None = None


@dataclass(frozen=True, slots=True)
class DataUpdate:
    source: str
    before: DataVersion
    after: DataVersion
    completed_at: datetime

    def message(self) -> str:
        lines = [
            "SeerAPI 数据更新成功",
            f"版本：{self.before.version} → {self.after.version}",
            f"完成时间：{self.completed_at.astimezone(TZ_CN):%Y-%m-%d %H:%M:%S}",
        ]
        if self.after.season is not None and self.after.season != self.before.season:
            start, end = (value.astimezone(TZ_CN) for value in self.after.season)
            lines.append(
                f"巅峰赛季：{start:%Y%m%d}（{start:%Y-%m-%d %H:%M}"
                f" 至 {end:%Y-%m-%d %H:%M}）"
            )
        return "\n".join(lines)
