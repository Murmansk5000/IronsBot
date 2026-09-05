# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the release-level new-content index from a Seer data database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import SQLAlchemyError

if TYPE_CHECKING:
    from sqlmodel import Session


class NewContentIndexRepositoryError(RuntimeError):
    """The published database does not expose a complete new-content index."""


@dataclass(frozen=True, slots=True)
class NewContentIndexItem:
    category: str
    entity_id: int
    name: str
    sort_value: int
    payload: dict[str, Any]
    change_kind: str


@dataclass(frozen=True, slots=True)
class NewContentIndexCategoryState:
    category: str
    comparison_ready: bool
    reason: str


@dataclass(frozen=True, slots=True)
class NewContentIndex:
    config_version: str
    weekly_cycle: str
    baseline_established: bool
    items: tuple[NewContentIndexItem, ...]
    category_states: tuple[NewContentIndexCategoryState, ...]


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

    return NewContentIndex(
        config_version=str(release["current_config_version"]),
        weekly_cycle=str(release["weekly_cycle"]),
        baseline_established=bool(release["baseline_established"]),
        items=tuple(_index_item(row) for row in rows),
        category_states=tuple(
            NewContentIndexCategoryState(
                category=str(row["category"]),
                comparison_ready=bool(row["comparison_ready"]),
                reason=str(row["reason"]),
            )
            for row in state_rows
        ),
    )


def _index_item(row: Any) -> NewContentIndexItem:
    try:
        payload = json.loads(str(row["payload_json"]))
    except json.JSONDecodeError:
        payload = {}
    return NewContentIndexItem(
        category=str(row["category"]),
        entity_id=int(row["entity_id"]),
        name=str(row["name"]),
        sort_value=int(row["sort_value"]),
        payload=payload if isinstance(payload, dict) else {},
        change_kind=str(row["change_kind"]),
    )
