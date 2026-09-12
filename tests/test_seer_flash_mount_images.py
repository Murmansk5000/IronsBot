from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.flash_mount_repository import (
    load_flash_mount_image,
)
from ironsbot.services.seer.data import PublishedDataIncompleteError

FLASH_TEST_MOUNT_ID = 1301170

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ironsbot.services.seer.data import SeerDataAccess


class _Data:
    def __init__(self, database: Path) -> None:
        self._engine = create_engine(f"sqlite:///{database}")

    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        with Session(self._engine) as session:
            yield operation(session)  # type: ignore[operator]


def test_load_flash_mount_image_reads_rendered_png(tmp_path: Path) -> None:
    database = tmp_path / "seerapi.sqlite"
    data = _Data(database)
    with data._engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE flash_mount_image ("
            "mount_id INTEGER PRIMARY KEY, png_data BLOB NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO flash_mount_image (mount_id, png_data) VALUES (?, ?)",
            (FLASH_TEST_MOUNT_ID, b"flash-mount"),
        )

    image = load_flash_mount_image(
        cast("SeerDataAccess", data), FLASH_TEST_MOUNT_ID
    )

    assert image == b"flash-mount"


def test_load_flash_mount_image_rejects_database_without_published_table(
    tmp_path: Path,
) -> None:
    with pytest.raises(PublishedDataIncompleteError) as raised:
        load_flash_mount_image(
            cast("SeerDataAccess", _Data(tmp_path / "old.sqlite")),
            FLASH_TEST_MOUNT_ID,
        )

    assert raised.value.component == "flash_mount_image"
    assert raised.value.entity_id == FLASH_TEST_MOUNT_ID
