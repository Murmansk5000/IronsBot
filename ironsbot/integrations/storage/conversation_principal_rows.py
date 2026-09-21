# SPDX-License-Identifier: MIT
"""Atomic row reconciliation for conversation-principal owned SQLite state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.integrations.storage.platform_identity import ConversationIdentityColumns
from ironsbot.integrations.storage.sqlite import quote_sqlite_identifier
from ironsbot.services.identity_principals import default_conversation_principal

if TYPE_CHECKING:
    import sqlite3

    from ironsbot.core.platform import ActorPrincipal, ConversationPrincipal

    PrincipalOwner = ActorPrincipal | ConversationPrincipal


class PrincipalRowSpecError(ValueError):
    def __init__(self) -> None:
        super().__init__("merge columns must be present in value_columns")


@dataclass(frozen=True, slots=True)
class PrincipalRowMergeSpec:
    table: str
    value_columns: tuple[str, ...]
    identity_columns: tuple[str, ...]
    order_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        quote_sqlite_identifier(self.table)
        for column in (
            *self.value_columns,
            *self.identity_columns,
            *self.order_columns,
        ):
            quote_sqlite_identifier(column)
        available = set(self.value_columns)
        if not set(self.identity_columns + self.order_columns) <= available:
            raise PrincipalRowSpecError


@dataclass(frozen=True, slots=True)
class PrincipalTableCopySpec:
    source_table: str
    target_table: str
    value_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        quote_sqlite_identifier(self.source_table)
        quote_sqlite_identifier(self.target_table)
        for column in self.value_columns:
            quote_sqlite_identifier(column)


def copy_conversation_rows_to_principals(
    connection: sqlite3.Connection,
    spec: PrincipalTableCopySpec,
) -> None:
    """Copy endpoint-owned rows into a freshly created principal-owned table."""

    endpoint_columns = (
        "conversation_platform",
        "conversation_account_id",
        "conversation_kind",
        "conversation_id",
    )
    columns = (*endpoint_columns, *spec.value_columns)
    selected = ", ".join(map(quote_sqlite_identifier, columns))
    source_sql = quote_sqlite_identifier(spec.source_table)
    rows = connection.execute(f"SELECT {selected} FROM {source_sql}").fetchall()
    inserted = ", ".join(
        map(
            quote_sqlite_identifier,
            ("principal_kind", "principal_id", *columns),
        )
    )
    target_sql = quote_sqlite_identifier(spec.target_table)
    placeholders = ", ".join("?" for _ in range(len(columns) + 2))
    for row in rows:
        conversation = ConversationIdentityColumns(
            *(str(value) for value in row[:4])
        ).to_conversation()
        principal = default_conversation_principal(conversation)
        connection.execute(
            f"INSERT INTO {target_sql} ({inserted}) VALUES ({placeholders})",
            (principal.kind, principal.id, *row),
        )


def merge_latest_principal_rows(
    connection: sqlite3.Connection,
    spec: PrincipalRowMergeSpec,
    *,
    source: PrincipalOwner,
    target: PrincipalOwner,
) -> None:
    """Merge rows by business key, retaining the newest row and its endpoint."""

    table_sql = quote_sqlite_identifier(spec.table)
    columns_sql = ", ".join(map(quote_sqlite_identifier, spec.value_columns))
    source_rows = connection.execute(
        f"SELECT {columns_sql} FROM {table_sql} "
        "WHERE principal_kind = ? AND principal_id = ?",
        (source.kind, source.id),
    ).fetchall()
    target_rows = connection.execute(
        f"SELECT {columns_sql} FROM {table_sql} "
        "WHERE principal_kind = ? AND principal_id = ?",
        (target.kind, target.id),
    ).fetchall()
    indexes = {column: index for index, column in enumerate(spec.value_columns)}
    identity_indexes = tuple(indexes[column] for column in spec.identity_columns)
    order_indexes = tuple(indexes[column] for column in spec.order_columns)
    selected: dict[tuple[object, ...], tuple[object, ...]] = {}
    for row in (*target_rows, *source_rows):
        values = tuple(row)
        identity = tuple(values[index] for index in identity_indexes)
        previous = selected.get(identity)
        if previous is None or _sort_key(values, order_indexes) > _sort_key(
            previous,
            order_indexes,
        ):
            selected[identity] = values

    delete_principal_rows(connection, spec.table, source)
    delete_principal_rows(connection, spec.table, target)
    inserted = ", ".join(
        map(
            quote_sqlite_identifier,
            ("principal_kind", "principal_id", *spec.value_columns),
        )
    )
    placeholders = ", ".join("?" for _ in range(len(spec.value_columns) + 2))
    for row in selected.values():
        connection.execute(
            f"INSERT INTO {table_sql} ({inserted}) VALUES ({placeholders})",
            (target.kind, target.id, *row),
        )


def delete_principal_rows(
    connection: sqlite3.Connection,
    table: str,
    principal: PrincipalOwner,
) -> None:
    table_sql = quote_sqlite_identifier(table)
    connection.execute(
        f"DELETE FROM {table_sql} WHERE principal_kind = ? AND principal_id = ?",
        (principal.kind, principal.id),
    )


def _sort_key(
    row: tuple[object, ...],
    indexes: tuple[int, ...],
) -> tuple[str, ...]:
    return tuple(str(row[index]) for index in indexes)
