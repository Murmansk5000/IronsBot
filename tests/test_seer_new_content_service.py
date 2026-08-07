from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from sqlmodel import Session, create_engine

from ironsbot.services.seer.new_content import (
    NEW_CONTENT_CATEGORIES,
    NewContentIndexUnavailableError,
    NewContentItem,
    NewContentService,
    format_new_content_category_count,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess


class FakeData:
    def __init__(self, path: Path) -> None:
        self._engine = create_engine(f"sqlite:///{path}")

    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        with Session(self._engine) as session:
            yield operation(session)  # type: ignore[operator]


def _service(path: Path) -> NewContentService:
    return NewContentService(cast("SeerDataAccess", FakeData(path)))


def test_reads_embedded_release_index_and_payload(tmp_path: Path) -> None:
    path = tmp_path / "seer.sqlite"
    service = _service(path)
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


def test_new_content_order_places_skills_before_mintmarks() -> None:
    assert NEW_CONTENT_CATEGORIES[:5] == (
        "pet",
        "pet_skin",
        "skill",
        "mintmark",
        "suit",
    )


def test_category_count_separates_additions_and_modifications() -> None:
    items = (
        NewContentItem("skill", 1, "新增技能", 1, {}, "added"),
        NewContentItem("skill", 2, "修改技能一", 2, {}, "modified"),
        NewContentItem("skill", 3, "修改技能二", 3, {}, "modified"),
    )

    assert format_new_content_category_count(items) == "1 项新增｜2 项修改"
    assert format_new_content_category_count(items[:1]) == "1 项新增"
    assert format_new_content_category_count(items[1:]) == "2 项修改"


def test_current_content_version_uses_shanghai_date_not_baseline() -> None:
    from ironsbot.services.seer.new_content import _current_content_date

    assert _current_content_date("20260730210447", "2026-07-24") == "2026-07-31"


def test_missing_index_is_explicitly_unavailable(tmp_path: Path) -> None:
    with pytest.raises(NewContentIndexUnavailableError):
        _service(tmp_path / "empty.sqlite").snapshot()
