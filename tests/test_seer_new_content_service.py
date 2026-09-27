from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.new_content_repository import (
    PublishedNewContentRepository,
)
from ironsbot.services.seer.new_content import (
    NEW_CONTENT_CATEGORIES,
    NewContentCategory,
    NewContentIndex,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentService,
    NewContentSnapshot,
    NewContentSnapshotChangedError,
    NewContentWeekExpiredError,
    format_new_content_category_count,
    format_new_content_item_description,
    new_content_category_preview_items,
)
from ironsbot.services.seer.new_content_menu import plan_new_content_menu

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess


class FakeData:
    def __init__(self, path: Path) -> None:
        self._engine = create_engine(f"sqlite:///{path}")

    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        with Session(self._engine) as session:
            yield operation(session)  # type: ignore[operator]


def test_official_preview_window_controls_content_visibility() -> None:
    class Repository:
        def load(self) -> NewContentIndex:
            return NewContentIndex(
                config_version="20260925185121",
                weekly_cycle="2026-09-24T10:00:00+08:00",
                baseline_established=True,
                items=(),
                category_states=(),
                cycle_start="2026-09-24T10:00:00+08:00",
                cycle_end="2026-10-02T00:00:00+08:00",
                cycle_status="syncing",
            )

    before_end = NewContentService(
        Repository(), now=lambda: datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
    ).snapshot()
    assert before_end.is_current_week
    assert plan_new_content_menu(before_end, ("pet",)) == (
        "新档期数据正在同步，稍后再查新增内容。"
    )
    after_end = NewContentService(
        Repository(), now=lambda: datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
    ).snapshot()
    assert not after_end.is_current_week
    assert after_end.cycle_status == "expired"


def _service(
    path: Path, *, now: Callable[[], datetime] | None = None
) -> NewContentService:
    return NewContentService(
        PublishedNewContentRepository(cast("SeerDataAccess", FakeData(path))),
        now=now,
    )


def test_reads_embedded_release_index_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "seer.sqlite"
    clock = [datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)]
    service = _service(path, now=lambda: clock[0])
    with Session(create_engine(f"sqlite:///{path}")) as session:
        session.connection().exec_driver_sql(
            """
            CREATE TABLE new_content_release (
                id INTEGER PRIMARY KEY, current_config_version TEXT,
                weekly_cycle TEXT, baseline_established INTEGER
            )
            """
        )
        session.connection().exec_driver_sql(
            """
            CREATE TABLE new_content_item (
                category TEXT, entity_id INTEGER, name TEXT, sort_value INTEGER,
                payload_json TEXT, change_kind TEXT
            )
            """
        )
        session.connection().exec_driver_sql(
            """
            CREATE TABLE new_content_category_state (
                category TEXT, comparison_ready INTEGER, reason TEXT
            )
            """
        )
        session.connection().exec_driver_sql(
            "INSERT INTO new_content_release VALUES (1, '20260731', '2026-07-31', 1)"
        )
        session.connection().exec_driver_sql(
            "CREATE TABLE seerapi_metadata (key TEXT PRIMARY KEY, value TEXT)"
        )
        session.connection().exec_driver_sql(
            "INSERT INTO seerapi_metadata VALUES "
            "('preview_cycle_start', '2026-07-31T00:00:00+08:00'), "
            "('preview_cycle_end', '2026-08-07T00:00:00+08:00'), "
            "('new_content_cycle_status', 'ready')"
        )
        session.connection().exec_driver_sql(
            """
            INSERT INTO new_content_item VALUES
                ('achievement', 6086031, '不动明王护法', 6086031,
                 '{"point": 0, "titles": [{"name": "不动明王护法"}]}', 'added'),
                ('pet_skin', 100, '测试皮肤', 100,
                 '{"pet_id": 1, "pet_name": "测试精灵", "resource_id": 100}',
                 'modified'),
                ('skill', 200, '测试技能', 200,
                 '{"power": 150, "max_pp": 5, "pets": [{"id": 1, "name": "测试精灵"}]}',
                 'added'),
                ('autocard_sanctuary_effect', 9, '潮涌', 9,
                 '{"sanctuary_id": 2, "sanctuary_name": "沧岚", "unlock_round": 5}',
                 'added')
            """
        )
        session.connection().exec_driver_sql(
            """
            INSERT INTO new_content_category_state VALUES
                ('pet', 1, 'ready'),
                ('autocard_sanctuary_effect', 0, 'first_observation')
            """
        )
        session.commit()

    snapshot = service.snapshot()

    assert snapshot.baseline_established is True
    assert snapshot.weekly_cycle == "2026-07-31"
    assert snapshot.source_weekly_cycle == "2026-07-31"
    assert snapshot.is_current_week
    assert snapshot.items_for("achievement")[0].payload["point"] == 0
    assert snapshot.items_for("pet_skin")[0].payload["pet_name"] == "测试精灵"
    assert snapshot.items_for("pet_skin")[0].change_kind == "modified"
    skill = snapshot.items_for("skill")[0]
    assert skill.name == "测试技能"
    assert skill.payload["pets"][0]["name"] == "测试精灵"
    effect = snapshot.items_for("autocard_sanctuary_effect")[0]
    assert effect.name == "潮涌"
    assert effect.payload["sanctuary_name"] == "沧岚"
    assert snapshot.is_category_comparable("pet") is True
    assert snapshot.is_category_comparable("autocard_sanctuary_effect") is False
    assert (
        snapshot.category_state("autocard_sanctuary_effect").reason
        == "first_observation"
    )
    service.require_snapshot(snapshot)

    # Rebuilt releases may retain the config version but correct index payloads.
    with Session(create_engine(f"sqlite:///{path}")) as session:
        session.connection().exec_driver_sql(
            "UPDATE new_content_item SET name = 'corrected' WHERE category = 'skill'"
        )
        session.commit()
    with pytest.raises(NewContentSnapshotChangedError):
        service.require_snapshot(snapshot)
    service.require_snapshot(service.snapshot())

    clock[0] = datetime(2026, 8, 6, 15, 59, tzinfo=timezone.utc)
    assert service.snapshot().is_current_week
    clock[0] = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)
    expired = service.snapshot()
    assert not expired.is_current_week
    assert expired.source_weekly_cycle == "2026-07-31"
    assert expired.items == ()
    assert expired.category_states == ()
    with pytest.raises(NewContentWeekExpiredError):
        service.require_snapshot(snapshot)
    with pytest.raises(NewContentWeekExpiredError):
        service.require_snapshot(expired)


def test_missing_official_cycle_never_exposes_legacy_weekly_items() -> None:
    class LegacyRepository:
        def load(self) -> NewContentIndex:
            return NewContentIndex(
                config_version="20260925",
                weekly_cycle="2026-09-25",
                baseline_established=True,
                items=(),
                category_states=(),
            )

    snapshot = NewContentService(LegacyRepository()).snapshot()
    assert not snapshot.is_current_week
    assert snapshot.cycle_status == "cycle_unavailable"
    assert plan_new_content_menu(snapshot, ("pet",)) == (
        "当前数据版本尚未提供官方预告档期，请更新 SeerAPI 数据。"
    )


def test_new_content_order_places_peak_pools_before_skins() -> None:
    assert NEW_CONTENT_CATEGORIES[:8] == (
        "pet",
        "peak_pool",
        "peak_expert_pool",
        "peak_master_pool",
        "pet_skin",
        "skill",
        "mintmark",
        "suit",
    )


@pytest.mark.parametrize("category", ["peak_pool", "peak_expert_pool"])
def test_peak_pool_change_description_distinguishes_zero_from_unlimited(
    category: NewContentCategory,
) -> None:
    change = NewContentItem(
        category,
        5000,
        "测试精灵",
        5000,
        {"previous_limit": 0, "current_limit": None},
        "modified",
    )

    assert format_new_content_item_description(change) == "修改｜5000｜限0 → 不限"


@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        (20, 6, "修改｜5000｜20 点 → 6 点"),
        (None, 35, "修改｜5000｜未列入 → 35 点"),
        (6, None, "修改｜5000｜6 点 → 未列入"),
    ],
)
def test_master_pool_change_description_uses_competitive_points(
    previous: int | None,
    current: int | None,
    expected: str,
) -> None:
    change = NewContentItem(
        "peak_master_pool",
        5000,
        "测试精灵",
        5000,
        {"previous_limit": previous, "current_limit": current},
        "modified",
    )

    assert format_new_content_item_description(change) == expected


def test_category_count_separates_additions_and_modifications() -> None:
    items = (
        NewContentItem("skill", 1, "新增技能", 1, {}, "added"),
        NewContentItem("skill", 2, "修改技能一", 2, {}, "modified"),
        NewContentItem("skill", 3, "修改技能二", 3, {}, "modified"),
    )

    assert format_new_content_category_count(items) == "1 项新增｜2 项修改"
    assert format_new_content_category_count(items[:1]) == "1 项新增"
    assert format_new_content_category_count(items[1:]) == "2 项修改"


def test_root_preview_keeps_additions_and_skips_new_pet_skills() -> None:
    new_pet = NewContentItem("pet", 100, "本周精灵", 100, {}, "added")
    new_pet_skill = NewContentItem(
        "skill",
        1,
        "本周精灵自带技能",
        1,
        {"pets": [{"id": 100, "name": "本周精灵"}]},
        "added",
    )
    existing_pet_skill = NewContentItem(
        "skill",
        2,
        "旧精灵新增技能",
        2,
        {"pets": [{"id": 200, "name": "旧精灵"}]},
        "added",
    )
    shared_skill = NewContentItem(
        "skill",
        3,
        "新旧精灵共用技能",
        3,
        {
            "pets": [
                {"id": 100, "name": "本周精灵"},
                {"id": 200, "name": "旧精灵"},
            ]
        },
        "added",
    )
    modified_skill = NewContentItem(
        "skill",
        4,
        "技能修正",
        4,
        {"pets": [{"id": 200, "name": "旧精灵"}]},
        "modified",
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260911",
        weekly_cycle="2026-09-11",
        items=(
            new_pet,
            new_pet_skill,
            existing_pet_skill,
            shared_skill,
            modified_skill,
        ),
    )

    assert new_content_category_preview_items(snapshot, "skill", 5) == (
        existing_pet_skill,
        shared_skill,
    )
    assert new_content_category_preview_items(snapshot, "skill", 1) == (
        existing_pet_skill,
    )
    assert new_content_category_preview_items(snapshot, "skill", 0) == ()


def test_missing_index_is_explicitly_unavailable(tmp_path: Path) -> None:
    with pytest.raises(NewContentIndexUnavailableError):
        _service(tmp_path / "empty.sqlite").snapshot()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("payload_json", "{"),
        ("payload_json", "[]"),
        ("category", "unsupported"),
        ("change_kind", "renamed"),
    ],
)
def test_malformed_index_item_is_explicitly_unavailable(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    path = tmp_path / "malformed.sqlite"
    with Session(create_engine(f"sqlite:///{path}")) as session:
        connection = session.connection()
        connection.exec_driver_sql(
            "CREATE TABLE new_content_release "
            "(id INTEGER PRIMARY KEY, current_config_version TEXT, "
            "weekly_cycle TEXT, baseline_established INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_item "
            "(category TEXT, entity_id INTEGER, name TEXT, sort_value INTEGER, "
            "payload_json TEXT, change_kind TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_category_state "
            "(category TEXT, comparison_ready INTEGER, reason TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_release VALUES (1, '20260731', '2026-07-31', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_item VALUES "
            "('skill', 1, '测试技能', 1, '{}', 'added')"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_category_state VALUES ('skill', 1, 'ready')"
        )
        connection.exec_driver_sql(
            f"UPDATE new_content_item SET {column} = ?",
            (value,),
        )
        session.commit()

    with pytest.raises(NewContentIndexUnavailableError):
        _service(path).snapshot()


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("new_content_release", "baseline_established"),
        ("new_content_category_state", "comparison_ready"),
    ],
)
def test_malformed_index_flag_is_explicitly_unavailable(
    tmp_path: Path,
    table: str,
    column: str,
) -> None:
    path = tmp_path / "malformed-flag.sqlite"
    with Session(create_engine(f"sqlite:///{path}")) as session:
        connection = session.connection()
        connection.exec_driver_sql(
            "CREATE TABLE new_content_release "
            "(id INTEGER PRIMARY KEY, current_config_version TEXT, "
            "weekly_cycle TEXT, baseline_established INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_item "
            "(category TEXT, entity_id INTEGER, name TEXT, sort_value INTEGER, "
            "payload_json TEXT, change_kind TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE new_content_category_state "
            "(category TEXT, comparison_ready INTEGER, reason TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_release VALUES (1, '20260731', '2026-07-31', 1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO new_content_category_state VALUES ('skill', 1, 'ready')"
        )
        connection.exec_driver_sql(f"UPDATE {table} SET {column} = 'true'")
        session.commit()

    with pytest.raises(NewContentIndexUnavailableError):
        _service(path).snapshot()


def test_index_without_category_states_is_explicitly_unavailable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy.sqlite"
    with Session(create_engine(f"sqlite:///{path}")) as session:
        session.connection().exec_driver_sql(
            """
            CREATE TABLE new_content_release (
                id INTEGER PRIMARY KEY, current_config_version TEXT,
                weekly_cycle TEXT, baseline_established INTEGER
            )
            """
        )
        session.connection().exec_driver_sql(
            """
            CREATE TABLE new_content_item (
                category TEXT, entity_id INTEGER, name TEXT, sort_value INTEGER,
                payload_json TEXT, change_kind TEXT
            )
            """
        )
        session.connection().exec_driver_sql(
            "INSERT INTO new_content_release VALUES (1, '20260731', '2026-07-31', 1)"
        )
        session.commit()

    with pytest.raises(NewContentIndexUnavailableError):
        _service(path).snapshot()
