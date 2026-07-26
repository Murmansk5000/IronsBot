from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.integrations.storage.achievement_history import (
    SqliteAchievementHistoryStore,
)
from ironsbot.services.seer.achievement_history import (
    AchievementHistoryService,
    AchievementRecord,
    AchievementSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.services.seer.data import SeerDataAccess

UTC = timezone.utc
EXPECTED_ACHIEVEMENT_COUNT = 2


def _achievement(
    achievement_id: int,
    name: str,
    *,
    hidden: bool = False,
) -> AchievementRecord:
    return AchievementRecord(
        achievement_id=achievement_id,
        name=name,
        point=10,
        description=f"完成{name}",
        is_hidden=hidden,
        type_name="其他类",
        branch_name="限定分类",
        title_name=name,
    )


def _snapshot(
    version: str,
    generated_at: datetime,
    *achievements: AchievementRecord,
) -> AchievementSnapshot:
    item_ids = ",".join(str(item.achievement_id) for item in achievements)
    return AchievementSnapshot(
        game_data_version=version,
        source_generated_at=generated_at,
        observed_at=generated_at,
        content_hash=f"{version}:{item_ids}",
        achievements=tuple(achievements),
    )


class FakeData:
    def __init__(
        self,
        value: tuple[
            str,
            datetime,
            tuple[AchievementRecord, ...],
        ],
    ) -> None:
        self.value = value

    @contextmanager
    def query(self, _operation: object) -> Iterator[object]:
        yield self.value


def _service(
    store: SqliteAchievementHistoryStore,
    version: str,
    generated_at: datetime,
    *achievements: AchievementRecord,
) -> AchievementHistoryService:
    data = FakeData((version, generated_at, tuple(achievements)))
    return AchievementHistoryService(
        cast("SeerDataAccess", data),
        store,
        clock=lambda: generated_at,
    )


def test_store_compares_whole_release_cycle_against_older_baseline(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
    )
    existing = _achievement(1, "已有成就")
    early_update = _achievement(2, "周四新增")
    delayed_update = _achievement(3, "周六新增")

    assert store.record(
        _snapshot(
            "202607170001",
            datetime(2026, 7, 17, 1, tzinfo=UTC),
            existing,
        )
    )
    assert store.record(
        _snapshot(
            "20260723220442",
            datetime(2026, 7, 23, 14, 4, 42, tzinfo=UTC),
            existing,
            early_update,
        )
    )
    comparison = store.compare_latest()
    assert comparison is not None
    assert [item.name for item in comparison.added] == ["周四新增"]

    assert store.record(
        _snapshot(
            "20260725152311",
            datetime(2026, 7, 25, 7, 23, 11, tzinfo=UTC),
            existing,
            early_update,
            delayed_update,
        )
    )
    comparison = store.compare_latest()
    assert comparison is not None
    assert [item.name for item in comparison.added] == [
        "周四新增",
        "周六新增",
    ]


def test_same_cycle_snapshot_is_not_used_as_four_day_baseline(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
        baseline_lookback_days=4,
    )
    existing = _achievement(1, "已有成就")
    early_update = _achievement(2, "周三提前新增")

    assert store.record(
        _snapshot(
            "202607170001",
            datetime(2026, 7, 17, 1, tzinfo=UTC),
            existing,
        )
    )
    assert store.record(
        _snapshot(
            "202607220001",
            datetime(2026, 7, 22, 1, tzinfo=UTC),
            existing,
            early_update,
        )
    )
    assert store.record(
        _snapshot(
            "202607260002",
            datetime(2026, 7, 26, 1, 2, tzinfo=UTC),
            existing,
            early_update,
        )
    )

    comparison = store.compare_latest()
    assert comparison is not None
    assert comparison.baseline is not None
    assert comparison.baseline.game_data_version == "202607170001"
    assert [item.name for item in comparison.added] == ["周三提前新增"]


def test_same_official_version_replaces_snapshot_instead_of_advancing_baseline(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
    )
    first = _achievement(1, "已有成就")
    parser_fix = _achievement(2, "解析补全")

    assert store.record(
        _snapshot(
            "202607240001",
            datetime(2026, 7, 24, 1, tzinfo=UTC),
            first,
        )
    )
    assert store.record(
        _snapshot(
            "202607240001",
            datetime(2026, 7, 24, 5, tzinfo=UTC),
            first,
            parser_fix,
        )
    )
    comparison = store.compare_latest()
    assert comparison is not None
    assert comparison.baseline is None
    assert comparison.current.achievement_count == EXPECTED_ACHIEVEMENT_COUNT

    assert store.record(
        _snapshot(
            "202607310001",
            datetime(2026, 7, 31, 5, tzinfo=UTC),
            first,
            parser_fix,
        )
    )
    comparison = store.compare_latest()
    assert comparison is not None
    assert comparison.added == ()


def test_generated_id_change_does_not_create_false_new_achievement(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
    )
    before = _achievement(1, "稳定成就")
    after = _achievement(999, "稳定成就")

    assert store.record(
        _snapshot(
            "202607170001",
            datetime(2026, 7, 17, 1, tzinfo=UTC),
            before,
        )
    )
    assert store.record(
        _snapshot(
            "202607240001",
            datetime(2026, 7, 24, 1, tzinfo=UTC),
            after,
        )
    )

    comparison = store.compare_latest()
    assert comparison is not None
    assert comparison.added == ()


@pytest.mark.asyncio
async def test_service_reports_no_new_achievements_for_new_official_version(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
    )
    existing = _achievement(1, "已有成就")
    first = _service(
        store,
        "202607170001",
        datetime(2026, 7, 17, 1, tzinfo=UTC),
        existing,
    )
    assert "已建立成就对比基线" in await first.new_achievements()

    second = _service(
        store,
        "202607240001",
        datetime(2026, 7, 24, 1, tzinfo=UTC),
        existing,
    )
    assert "本次周更未发现新增成就" in await second.new_achievements()


@pytest.mark.asyncio
async def test_service_formats_added_hidden_achievement(
    tmp_path: Path,
) -> None:
    store = SqliteAchievementHistoryStore(
        tmp_path / "history.sqlite",
        max_snapshots=32,
    )
    existing = _achievement(1, "已有成就")
    await _service(
        store,
        "202607170001",
        datetime(2026, 7, 17, 1, tzinfo=UTC),
        existing,
    ).new_achievements()
    message = await _service(
        store,
        "202607240001",
        datetime(2026, 7, 24, 1, tzinfo=UTC),
        existing,
        _achievement(2, "秘密成就", hidden=True),
    ).new_achievements()

    assert "官方版本" not in message
    assert "当前数据" not in message
    assert "更新前基线" not in message
    assert "共发现 1 项" in message
    assert "秘密成就（10点，隐藏）" in message
    assert "完成秘密成就" in message
