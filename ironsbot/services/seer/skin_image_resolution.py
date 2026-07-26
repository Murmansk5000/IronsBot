# SPDX-License-Identifier: MIT
"""Read build-time classic-skin image resolution data from IronsBot SQLite."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlmodel import Session

logger = logging.getLogger(__name__)
_missing_table_warning_logged = False


@dataclass(frozen=True, slots=True)
class SkinImageResolution:
    skin_id: int
    head_resource_id: int
    body_resource_id: int
    head_resolution: str
    body_resolution: str
    source_pet_id: int | None


def load_skin_image_resolutions(
    session: Session,
    skin_ids: Iterable[int],
) -> dict[int, SkinImageResolution]:
    """Load build-time resolutions, falling back cleanly for legacy databases."""

    resolved_skin_ids = tuple(sorted({int(skin_id) for skin_id in skin_ids if skin_id}))
    if not resolved_skin_ids:
        return {}
    statement = text(
        """
        SELECT
            skin_id,
            head_resource_id,
            body_resource_id,
            head_resolution,
            body_resolution,
            source_pet_id
        FROM skin_image_resolution
        WHERE skin_id IN :skin_ids
        """
    ).bindparams(bindparam("skin_ids", expanding=True))
    try:
        rows = session.execute(
            statement,
            params={"skin_ids": resolved_skin_ids},
        ).all()
    except SQLAlchemyError as error:
        _log_resolution_load_failure(error)
        return {}

    result: dict[int, SkinImageResolution] = {}
    for row in rows:
        mapping = cast(
            "Mapping[str, Any]",
            row._mapping if hasattr(row, "_mapping") else row,
        )
        skin_id = int(mapping["skin_id"])
        result[skin_id] = SkinImageResolution(
            skin_id=skin_id,
            head_resource_id=int(mapping["head_resource_id"] or 0),
            body_resource_id=int(mapping["body_resource_id"] or 0),
            head_resolution=str(mapping["head_resolution"]),
            body_resolution=str(mapping["body_resolution"]),
            source_pet_id=(
                int(mapping["source_pet_id"])
                if mapping["source_pet_id"] is not None
                else None
            ),
        )
    return result


def _log_resolution_load_failure(error: SQLAlchemyError) -> None:
    global _missing_table_warning_logged  # noqa: PLW0603 - process-wide legacy DB warning

    message = str(error).lower()
    if "skin_image_resolution" in message and "no such table" in message:
        if not _missing_table_warning_logged:
            logger.warning(
                "skin image resolution table is absent; using original skin "
                "resource IDs until data is updated"
            )
            _missing_table_warning_logged = True
        return
    logger.exception("failed to load build-time skin image resolutions")
