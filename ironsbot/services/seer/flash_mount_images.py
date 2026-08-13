# SPDX-License-Identifier: MIT
"""Read optional build-time Flash mount PNG fallbacks from SeerAPI data."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataAccess

logger = logging.getLogger(__name__)
_missing_table_warning_logged = False


def load_flash_mount_image(data: SeerDataAccess, mount_id: int) -> bytes | None:
    """Return a rendered Flash PNG, or ``None`` for old and incomplete data DBs."""

    if mount_id <= 0:
        return None
    try:
        with data.query(
            lambda session: _load_flash_mount_image(session, mount_id)
        ) as image:
            return image
    except (AttributeError, RuntimeError, SQLAlchemyError) as error:
        _log_load_failure(error)
        return None


def _load_flash_mount_image(session: Session, mount_id: int) -> bytes | None:
    row = session.connection().exec_driver_sql(
        "SELECT png_data FROM flash_mount_image WHERE mount_id = ?",
        (mount_id,),
    ).first()
    return None if row is None else bytes(row[0])


def _log_load_failure(error: Exception) -> None:
    global _missing_table_warning_logged  # noqa: PLW0603 - process-wide warning

    message = str(error).lower()
    if "flash_mount_image" in message and "no such table" in message:
        if not _missing_table_warning_logged:
            logger.warning(
                "Flash mount fallback table is absent; waiting for a newer "
                "SeerAPI data database"
            )
            _missing_table_warning_logged = True
        return
    logger.exception("failed to load Flash mount fallback image", exc_info=error)
