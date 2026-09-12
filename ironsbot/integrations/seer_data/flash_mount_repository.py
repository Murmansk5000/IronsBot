# SPDX-License-Identifier: GPL-3.0-or-later
"""Read build-time Flash mount PNGs from SeerAPI data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.data import PublishedDataIncompleteError

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader

def load_flash_mount_image(data: SeerDataReader, mount_id: int) -> bytes | None:
    """Return a published PNG while preserving missing-row semantics."""

    if mount_id <= 0:
        return None
    try:
        with data.query(
            lambda session: _load_flash_mount_image(session, mount_id)
        ) as image:
            return image
    except (AttributeError, RuntimeError, SQLAlchemyError) as error:
        raise PublishedDataIncompleteError(
            "flash_mount_image", entity_id=mount_id
        ) from error


def _load_flash_mount_image(session: Session, mount_id: int) -> bytes | None:
    row = session.connection().exec_driver_sql(
        "SELECT png_data FROM flash_mount_image WHERE mount_id = ?",
        (mount_id,),
    ).first()
    return None if row is None else bytes(row[0])
