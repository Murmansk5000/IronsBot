from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from sqlmodel import Session, create_engine

from ironsbot.services.seer.flash_mount_images import load_flash_mount_image

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
            (1301170, b"flash-mount"),
        )

    image = load_flash_mount_image(cast("SeerDataAccess", data), 1301170)

    assert image == b"flash-mount"


def test_load_flash_mount_image_allows_old_database(tmp_path: Path) -> None:
    image = load_flash_mount_image(
        cast("SeerDataAccess", _Data(tmp_path / "old.sqlite")),
        1301170,
    )

    assert image is None
