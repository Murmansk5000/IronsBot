# SPDX-License-Identifier: MIT
"""Release-level compatibility checks for published SeerAPI databases."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

SEERAPI_SCHEMA_CONTRACT_VERSION = "1"
_SCHEMA_CONTRACT_KEY = "ironsbot_schema_contract_version"
_REQUIRED_TABLES: frozenset[str] = frozenset(("api_metadata", "ironsbot_metadata"))


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
        version = connection.execute(
            text("SELECT value FROM ironsbot_metadata WHERE key = :key"),
            {"key": _SCHEMA_CONTRACT_KEY},
        ).scalar_one_or_none()

    if version != SEERAPI_SCHEMA_CONTRACT_VERSION:
        raise SeerApiReleaseContractError.incompatible_schema_version(version)
