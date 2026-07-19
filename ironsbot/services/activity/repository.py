# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from collections.abc import Mapping

ACTIVITY_REQUIRED_COLUMNS = frozenset(
    {"id", "name", "end_time", "is_show", "sort_order"}
)
_LOGGER = logging.getLogger(__name__)


def _warn_activity_data_unavailable(
    logged_warnings: set[str],
    key: str,
    reason: str,
) -> None:
    if key in logged_warnings:
        return

    _LOGGER.warning("activity reminder skipped: %s", reason)
    logged_warnings.add(key)


def _activity_table_columns(session: Any) -> set[str]:
    rows = session.execute(text("PRAGMA table_info(activity)")).mappings().all()
    return {str(row["name"]) for row in rows if row.get("name") is not None}


def _load_activity_rows(
    session: Any | None,
    logged_warnings: set[str],
    *,
    only_shown: bool,
) -> list[Mapping[str, Any]]:
    if session is None:
        _warn_activity_data_unavailable(
            logged_warnings,
            "missing_session",
            "SeerAPI database not ready",
        )
        return []

    try:
        columns = _activity_table_columns(session)
        if not columns:
            _warn_activity_data_unavailable(
                logged_warnings,
                "missing_table",
                (
                    "activity table missing in SeerAPI database; run /更新数据 "
                    "after the data release is available, or set "
                    "activity.enabled=false"
                ),
            )
            return []

        missing_columns = ACTIVITY_REQUIRED_COLUMNS - columns
        if missing_columns:
            _warn_activity_data_unavailable(
                logged_warnings,
                "invalid_schema",
                (
                    "activity table schema is missing columns: "
                    f"{', '.join(sorted(missing_columns))}"
                ),
            )
            return []

        if "start_time" in columns and only_shown:
            query = text(
                """
                SELECT id, name, start_time, end_time, is_show, sort_order
                FROM activity
                WHERE end_time IS NOT NULL
                  AND COALESCE(is_show, 0) != 0
                ORDER BY end_time, sort_order, id
                """
            )
        elif "start_time" in columns:
            query = text(
                """
                SELECT id, name, start_time, end_time, is_show, sort_order
                FROM activity
                WHERE end_time IS NOT NULL
                ORDER BY end_time, sort_order, id
                """
            )
        elif only_shown:
            query = text(
                """
                SELECT id, name, end_time, is_show, sort_order
                FROM activity
                WHERE end_time IS NOT NULL
                  AND COALESCE(is_show, 0) != 0
                ORDER BY end_time, sort_order, id
                """
            )
        else:
            query = text(
                """
                SELECT id, name, end_time, is_show, sort_order
                FROM activity
                WHERE end_time IS NOT NULL
                ORDER BY end_time, sort_order, id
                """
            )

        rows = session.execute(query).mappings().all()
    except OperationalError as e:
        _LOGGER.debug("activity reminder query failed", exc_info=True)
        _warn_activity_data_unavailable(
            logged_warnings,
            "query_failed",
            f"activity table query failed: {e.__class__.__name__}",
        )
        return []

    logged_warnings.difference_update(
        {"missing_session", "missing_table", "invalid_schema", "query_failed"}
    )
    return list(rows)


@dataclass(slots=True)
class ActivityRepository:
    _logged_warnings: set[str] = field(default_factory=set)

    def load(
        self,
        session: Any | None,
        *,
        only_shown: bool,
    ) -> list[Mapping[str, Any]]:
        return _load_activity_rows(
            session,
            self._logged_warnings,
            only_shown=only_shown,
        )
