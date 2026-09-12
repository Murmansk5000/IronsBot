# SPDX-License-Identifier: MIT
"""Release-level compatibility checks for published SeerAPI databases."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection, Engine

SEERAPI_SCHEMA_CONTRACT_VERSION = "1"
_SCHEMA_CONTRACT_KEY = "ironsbot_schema_contract_version"
_SCHEMA_TABLES_KEY = "ironsbot_schema_tables"
_SCHEMA_FINGERPRINT_KEY = "ironsbot_schema_fingerprint"
_REQUIRED_TABLES: frozenset[str] = frozenset(
    (
        "api_metadata",
        "ironsbot_metadata",
        "item",
        "mintmark",
        "peak_pool",
        "pet",
        "skill",
    )
)


class SeerApiReleaseContractError(ValueError):
    """Raised when a published SeerAPI database cannot be safely loaded."""

    @classmethod
    def missing_tables(cls, tables: list[str]) -> SeerApiReleaseContractError:
        return cls(f"SeerAPI 发布数据库缺少必需表: {', '.join(tables)}")

    @classmethod
    def incompatible_schema_version(
        cls,
        version: str | None,
    ) -> SeerApiReleaseContractError:
        return cls(
            "SeerAPI 发布数据库 schema 契约版本不兼容: "
            f"期望 {SEERAPI_SCHEMA_CONTRACT_VERSION}，实际 {version!r}"
        )

    @classmethod
    def invalid_metadata(cls, field: str) -> SeerApiReleaseContractError:
        return cls(f"SeerAPI 发布数据库元数据无效: {field}")

    @classmethod
    def missing_api_metadata(cls) -> SeerApiReleaseContractError:
        return cls.invalid_metadata("api_metadata row")

    @classmethod
    def invalid_render_manifest(cls) -> SeerApiReleaseContractError:
        return cls.invalid_metadata("render asset manifest")

    @classmethod
    def invalid_schema_manifest(cls) -> SeerApiReleaseContractError:
        return cls.invalid_metadata("schema table manifest")


def _schema_fingerprint(connection: Connection, tables: tuple[str, ...]) -> str:
    table_set = set(tables)
    rows = tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT type, name, tbl_name, COALESCE(sql, '') "
                "FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' "
                "AND type IN ('table', 'index', 'trigger') "
                "ORDER BY type, name"
            )
        )
        if str(row[2]) in table_set
    )
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode()).hexdigest()


def _parse_schema_tables(value: str | None) -> tuple[str, ...]:
    try:
        raw = json.loads(value or "")
    except (TypeError, json.JSONDecodeError) as error:
        raise SeerApiReleaseContractError.invalid_schema_manifest() from error
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(table, str) or not table for table in raw)
    ):
        raise SeerApiReleaseContractError.invalid_schema_manifest()
    tables = tuple(raw)
    if tables != tuple(sorted(set(tables))):
        raise SeerApiReleaseContractError.invalid_schema_manifest()
    return tables


def validate_published_seerapi_release(engine: Engine) -> None:
    """Reject a staged database that does not meet the consumer contract."""

    with engine.connect() as connection:
        tables = {
            str(name)
            for name in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        }
        missing_tables = sorted(_REQUIRED_TABLES - tables)
        if missing_tables:
            raise SeerApiReleaseContractError.missing_tables(missing_tables)
        metadata = dict(
            connection.execute(
                text(
                    "SELECT key, value FROM ironsbot_metadata "
                    "WHERE key IN (:version_key, :tables_key, :fingerprint_key)"
                ),
                {
                    "version_key": _SCHEMA_CONTRACT_KEY,
                    "tables_key": _SCHEMA_TABLES_KEY,
                    "fingerprint_key": _SCHEMA_FINGERPRINT_KEY,
                },
            ).tuples().all()
        )

    version = metadata.get(_SCHEMA_CONTRACT_KEY)
    if version != SEERAPI_SCHEMA_CONTRACT_VERSION:
        raise SeerApiReleaseContractError.incompatible_schema_version(version)
    declared_tables = _parse_schema_tables(metadata.get(_SCHEMA_TABLES_KEY))
    if not _REQUIRED_TABLES.issubset(declared_tables):
        raise SeerApiReleaseContractError.invalid_schema_manifest()
    if not set(declared_tables).issubset(tables):
        raise SeerApiReleaseContractError.missing_tables(
            sorted(set(declared_tables) - tables)
        )
    with engine.connect() as connection:
        fingerprint = _schema_fingerprint(connection, declared_tables)
    if metadata.get(_SCHEMA_FINGERPRINT_KEY) != fingerprint:
        raise SeerApiReleaseContractError.invalid_schema_manifest()
