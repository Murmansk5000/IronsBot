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
    generated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DataUpdate:
    source: str
    before: DataVersion
    after: DataVersion
    completed_at: datetime

    def message(self) -> str:
        label = {"seerapi": "游戏", "aliases": "别名"}[self.source]
        generated_at = self.after.generated_at
        timestamp = (
            f"{generated_at.astimezone(TZ_CN):%Y-%m-%d %H:%M:%S}（北京时间）"
            if generated_at is not None and generated_at.tzinfo is not None
            else "未知"
        )
        return f"📢{label}数据已更新，可查询最新数据\n数据时间：{timestamp}"
