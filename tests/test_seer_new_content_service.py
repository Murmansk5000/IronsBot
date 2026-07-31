from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from sqlmodel import Session, create_engine

from ironsbot.services.seer.new_content import (
    NewContentIndexUnavailableError,
    NewContentService,
)


class FakeData:
    def __init__(self, path: Path) -> None:
        self._engine = create_engine(f"sqlite:///{path}")

    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        with Session(self._engine) as session:
            yield operation(session)  # type: ignore[operator]


def _service(path: Path) -> NewContentService:
    return NewContentService(cast("object", FakeData(path)))


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
            "INSERT INTO new_content_release VALUES (1, '20260731', '2026-07-31', 1)"
        )
        session.connection().exec_driver_sql(
            """
            INSERT INTO new_content_item VALUES
                ('achievement', 6086031, '不动明王护法', 6086031,
                 '{"point": 0, "titles": [{"name": "不动明王护法"}]}', 'added'),
                ('pet_skin', 100, '测试皮肤', 100,
                 '{"pet_id": 1, "pet_name": "测试精灵", "resource_id": 100}',
                 'modified')
            """
        )
        session.commit()

    snapshot = service.snapshot()

    assert snapshot.baseline_established is True
    assert snapshot.weekly_cycle == "2026-07-31"
    assert snapshot.items_for("achievement")[0].payload["point"] == 0
    assert snapshot.items_for("pet_skin")[0].payload["pet_name"] == "测试精灵"
    assert snapshot.items_for("pet_skin")[0].change_kind == "modified"


def test_missing_index_is_explicitly_unavailable(tmp_path: Path) -> None:
    with pytest.raises(NewContentIndexUnavailableError):
        _service(tmp_path / "empty.sqlite").snapshot()
