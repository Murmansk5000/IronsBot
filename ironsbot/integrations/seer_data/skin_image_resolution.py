# SPDX-License-Identifier: MIT
"""Read build-time classic-skin image resolution data from IronsBot SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from sqlmodel import Session


@dataclass(frozen=True, slots=True)
class SkinImageResolution:
    skin_id: int
    head_resource_id: int
    body_resource_id: int
    head_resolution: str
    body_resolution: str
    source_pet_id: int | None


class SkinImageResolutionSchemaError(RuntimeError):
    """The published Seer release lacks required skin-resolution facts."""

    def __init__(self) -> None:
        super().__init__("published Seer data is missing skin image resolution facts")


def load_skin_image_resolutions(
    session: Session,
    skin_ids: Iterable[int],
) -> dict[int, SkinImageResolution]:
    """Load required build-time skin image resolutions from the release."""

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
        raise SkinImageResolutionSchemaError from error

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
