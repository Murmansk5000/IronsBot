# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the release-level new-content index from a Seer data database."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

from ironsbot.core.value_coercion import require_bool_flag, require_int
from ironsbot.services.seer.new_content import (
    NewContentIndex,
    NewContentIndexCategoryState,
    NewContentIndexItem,
    NewContentIndexRepositoryError,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader


class PublishedNewContentRepository:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def load(self) -> NewContentIndex:
        with self._data.query(load_new_content_index) as index:
            return index


def load_new_content_index(session: Session) -> NewContentIndex:
    """Load raw release facts without assigning bot-facing category meaning."""

    try:
        connection = session.connection()
        release = (
            connection.exec_driver_sql(
                """
                SELECT current_config_version, weekly_cycle, baseline_established
                FROM new_content_release
                WHERE id = 1
                """
            )
            .mappings()
            .first()
        )
        if release is None:
            raise NewContentIndexRepositoryError
        rows = (
            connection.exec_driver_sql(
                """
                SELECT category, entity_id, name, sort_value, payload_json, change_kind
                FROM new_content_item
                ORDER BY category, sort_value, entity_id
                """
            )
            .mappings()
            .all()
        )
        has_category_state = connection.exec_driver_sql(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'new_content_category_state'
            """
        ).first()
        if not has_category_state:
            raise NewContentIndexRepositoryError
        state_rows = (
            connection.exec_driver_sql(
                """
                SELECT category, comparison_ready, reason
                FROM new_content_category_state
                ORDER BY category
                """
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError as error:
        raise NewContentIndexRepositoryError from error

    try:
        return NewContentIndex(
            config_version=str(release["current_config_version"]),
            weekly_cycle=str(release["weekly_cycle"]),
            baseline_established=require_bool_flag(
                release["baseline_established"],
                field="new_content_release.baseline_established",
            ),
            items=tuple(_index_item(row) for row in rows),
            category_states=tuple(
                NewContentIndexCategoryState(
                    category=str(row["category"]),
                    comparison_ready=require_bool_flag(
                        row["comparison_ready"],
                        field="new_content_category_state.comparison_ready",
                    ),
                    reason=str(row["reason"]),
                )
                for row in state_rows
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise NewContentIndexRepositoryError from error


def _index_item(row: Any) -> NewContentIndexItem:
    payload = json.loads(str(row["payload_json"]))
    if not isinstance(payload, dict):
        raise TypeError("new_content_item.payload_json")
    return NewContentIndexItem(
        category=str(row["category"]),
        entity_id=require_int(row["entity_id"], field="new_content_item.entity_id"),
        name=str(row["name"]),
        sort_value=require_int(row["sort_value"], field="new_content_item.sort_value"),
        payload=payload,
        change_kind=str(row["change_kind"]),
    )
