# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot.log import logger
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

ACTIVITY_REQUIRED_COLUMNS = frozenset(
    {"id", "name", "end_time", "is_show", "sort_order"}
)
_logged_warnings: set[str] = set()


def _warn_activity_data_unavailable(key: str, reason: str) -> None:
    if key in _logged_warnings:
        return

    logger.warning(f"activity reminder skipped: {reason}")
    _logged_warnings.add(key)


def _activity_table_columns(session: Any) -> set[str]:
    rows = session.execute(text("PRAGMA table_info(activity)")).mappings().all()
    return {str(row["name"]) for row in rows if row.get("name") is not None}


def load_activity_rows(
    session_provider: Callable[[str], Any | None],
    *,
    database_name: str,
    only_shown: bool,
) -> list[Mapping[str, Any]]:
    gen = session_provider(database_name)
    if gen is None:
        _warn_activity_data_unavailable(
            "missing_session",
            "SeerAPI database not ready",
        )
        return []

    where_clause = "WHERE end_time IS NOT NULL"
    if only_shown:
        where_clause += " AND COALESCE(is_show, 0) != 0"

    try:
        session = next(gen)
        columns = _activity_table_columns(session)
        if not columns:
            _warn_activity_data_unavailable(
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
                "invalid_schema",
                (
                    "activity table schema is missing columns: "
                    f"{', '.join(sorted(missing_columns))}"
                ),
            )
            return []

        select_column_names = ["id", "name"]
        if "start_time" in columns:
            select_column_names.append("start_time")
        select_column_names.extend(["end_time", "is_show", "sort_order"])

        rows = session.execute(
            text(
                f"SELECT {', '.join(select_column_names)} "
                f"FROM activity {where_clause} "
                "ORDER BY end_time, sort_order, id"
            )
        ).mappings().all()
    except OperationalError as e:
        logger.opt(exception=True).debug("activity reminder query failed")
        _warn_activity_data_unavailable(
            "query_failed",
            f"activity table query failed: {e.__class__.__name__}",
        )
        return []
    finally:
        gen.close()

    _logged_warnings.discard("missing_session")
    _logged_warnings.discard("missing_table")
    _logged_warnings.discard("invalid_schema")
    _logged_warnings.discard("query_failed")
    return list(rows)
