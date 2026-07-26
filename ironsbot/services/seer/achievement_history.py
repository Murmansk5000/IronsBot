# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol, cast

from seerapi_models import AchievementORM, ApiMetadataORM
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ironsbot.core.time import now
from ironsbot.services.seer.data import DataUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess

MAX_DISPLAY_ACHIEVEMENTS = 50
CONFIG_PACKAGE_VERSION_KEY = "config_package_version"


@dataclass(frozen=True, slots=True)
class AchievementRecord:
    achievement_id: int
    name: str
    point: int
    description: str
    is_hidden: bool
    type_name: str
    branch_name: str
    title_name: str

    def fingerprint_parts(self) -> tuple[str, ...]:
        return (
            str(self.achievement_id),
            self.name,
            str(self.point),
            self.description,
            "1" if self.is_hidden else "0",
            self.type_name,
            self.branch_name,
            self.title_name,
        )


@dataclass(frozen=True, slots=True)
class AchievementSnapshot:
    game_data_version: str
    source_generated_at: datetime
    observed_at: datetime
    content_hash: str
    achievements: tuple[AchievementRecord, ...]


@dataclass(frozen=True, slots=True)
class AchievementSnapshotVersion:
    snapshot_id: int
    game_data_version: str
    source_generated_at: datetime
    observed_at: datetime
    achievement_count: int


@dataclass(frozen=True, slots=True)
class AchievementComparison:
    current: AchievementSnapshotVersion
    baseline: AchievementSnapshotVersion | None
    added: tuple[AchievementRecord, ...]


class AchievementHistoryStore(Protocol):
    def record(self, snapshot: AchievementSnapshot) -> bool: ...

    def compare_latest(self) -> AchievementComparison | None: ...


class AchievementHistoryService:
    def __init__(
        self,
        data: SeerDataAccess,
        store: AchievementHistoryStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._data = data
        self._store = store
        self._clock = clock or (lambda: now(tz=timezone.utc))

    def capture_current_snapshot(self) -> bool:
        with self._data.query(load_achievement_snapshot) as loaded:
            game_data_version, source_generated_at, achievements = loaded
        if source_generated_at is None:
            raise DataUnavailableError
        snapshot = AchievementSnapshot(
            game_data_version=(
                game_data_version.strip()
                or f"generated:{_as_utc(source_generated_at).isoformat()}"
            ),
            source_generated_at=_as_utc(source_generated_at),
            observed_at=_as_utc(self._clock()),
            content_hash=_achievement_hash(achievements),
            achievements=achievements,
        )
        return self._store.record(snapshot)

    async def new_achievements(self) -> str:
        self.capture_current_snapshot()
        comparison = self._store.compare_latest()
        if comparison is None:
            raise DataUnavailableError
        return format_achievement_comparison(comparison)


def load_achievement_snapshot(
    session: Session,
) -> tuple[str, datetime | None, tuple[AchievementRecord, ...]]:
    metadata = session.exec(select(ApiMetadataORM)).first()
    game_data_version = _load_config_package_version(session)
    statement = (
        select(AchievementORM)
        .options(
            selectinload(cast("Any", AchievementORM.type)),
            selectinload(cast("Any", AchievementORM.branch)),
            selectinload(cast("Any", AchievementORM.title_part)),
        )
        .order_by(cast("Any", AchievementORM.id))
    )
    achievements = tuple(
        AchievementRecord(
            achievement_id=achievement.id,
            name=achievement.name.strip(),
            point=achievement.point,
            description=achievement.desc.strip(),
            is_hidden=achievement.is_hide,
            type_name=achievement.type.name.strip(),
            branch_name=achievement.branch.name.strip(),
            title_name=(
                ""
                if achievement.title_part is None
                else achievement.title_part.name.strip()
            ),
        )
        for achievement in session.exec(statement).all()
    )
    generated_at = None if metadata is None else metadata.generate_time
    return game_data_version, generated_at, achievements


def format_achievement_comparison(comparison: AchievementComparison) -> str:
    if comparison.baseline is None:
        return (
            "【新增成就】\n"
            f"已建立成就对比基线，当前共收录 "
            f"{comparison.current.achievement_count} 项；"
            "暂时缺少满足周更周期和时间间隔要求的历史快照，"
            "下次官方配置版本更新后即可准确比较。"
        )

    if not comparison.added:
        return "【新增成就】\n本次周更未发现新增成就。"

    lines = ["【新增成就】", f"共发现 {len(comparison.added)} 项："]
    visible = comparison.added[:MAX_DISPLAY_ACHIEVEMENTS]
    for index, achievement in enumerate(visible, start=1):
        flags = [f"{achievement.point}点"]
        if achievement.is_hidden:
            flags.append("隐藏")
        lines.append(f"{index}. {achievement.name}（{'，'.join(flags)}）")
        if achievement.description:
            lines.append(f"   {achievement.description}")
        if achievement.title_name and achievement.title_name != achievement.name:
            lines.append(f"   称号：{achievement.title_name}")
    hidden_count = len(comparison.added) - len(visible)
    if hidden_count > 0:
        lines.append(f"另有 {hidden_count} 项未显示。")
    return "\n".join(lines)


def _achievement_hash(achievements: tuple[AchievementRecord, ...]) -> str:
    digest = hashlib.sha256()
    for achievement in achievements:
        digest.update("\x1f".join(achievement.fingerprint_parts()).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _load_config_package_version(session: Session) -> str:
    try:
        row = session.connection().exec_driver_sql(
            """
            SELECT value
            FROM ironsbot_metadata
            WHERE key = ?
            """,
            (CONFIG_PACKAGE_VERSION_KEY,),
        ).first()
    except SQLAlchemyError:
        return ""
    if row is None:
        return ""
    return str(row[0]).strip()
