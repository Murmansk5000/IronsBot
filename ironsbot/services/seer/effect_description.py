# SPDX-License-Identifier: GPL-3.0-or-later
"""Read official named-effect descriptions added to the IronsBot data DB."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.orm import Session

EFFECT_DESCRIPTION_TABLE = "effect_description"
logger = logging.getLogger(__name__)


def load_effect_descriptions(session: Session) -> dict[str, str]:
    """Return official descriptions keyed by named effect.

    Older data releases do not include this enrichment table. Cards still
    render in that case, but unknown named effects have no expanded text.
    """

    statement = text(
        f"""
        SELECT name, description
        FROM {EFFECT_DESCRIPTION_TABLE}
        WHERE name <> '' AND description <> ''
        ORDER BY effect_id
        """
    )
    try:
        rows = session.execute(statement).all()
    except SQLAlchemyError:
        logger.debug(
            "official effect description data is unavailable "
            "in the current SQLite release",
            exc_info=True,
        )
        return {}

    result: dict[str, str] = {}
    for row in rows:
        mapping = cast(
            "Mapping[str, Any]",
            row._mapping if hasattr(row, "_mapping") else row,
        )
        name = str(mapping["name"] or "").strip()
        description = str(mapping["description"] or "").strip()
        if name and description:
            result.setdefault(name, description)
    return result
