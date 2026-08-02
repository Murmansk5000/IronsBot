# SPDX-License-Identifier: MIT
"""One-time offline migration into the consolidated state databases."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from ironsbot.integrations.storage.activity import ActivitySentStore
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.player_bindings import (
    SqlitePlayerBindingStore,
)
from ironsbot.integrations.storage.player_query_limits import (
    SqlitePlayerQueryLimitStore,
)
from ironsbot.integrations.storage.push_subscriptions import (
    PushUnsubscribeStore,
)
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.integrations.storage.sqlite import (
    SqliteDatabase,
    SqliteMigration,
    open_sqlite_connection,
    quote_sqlite_identifier,
)
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.integrations.storage.team_resources import (
    TeamResourceSubscriptionStore,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

StateTarget = Literal["qq", "runtime"]

QQ_STATE_NAMESPACES = frozenset(
    {
        "bilibili_preferences",
        "player_bindings",
        "player_query_limits",
        "push_subscriptions",
        "rank_display",
        "team_resources",
    }
)
RUNTIME_STATE_NAMESPACES = frozenset(
    {"activity_reminder", "skin_window", "team_audit"}
)


class StateMigrationError(RuntimeError):
    @classmethod
    def same_target(cls) -> StateMigrationError:
        return cls("QQ state and runtime state paths must differ")

    @classmethod
    def targets_with_legacy(cls) -> StateMigrationError:
        return cls(
            "consolidated state databases already exist while legacy files remain; "
            "refusing to overwrite newer state"
        )

    @classmethod
    def incompatible_table(cls, table: str) -> StateMigrationError:
        return cls(f"no compatible columns found for {table}")

    @classmethod
    def row_count_mismatch(
        cls,
        table: str,
        actual: int,
        expected: int,
    ) -> StateMigrationError:
        return cls(f"row count mismatch for {table}: {actual} != {expected}")

    @classmethod
    def partial_targets(cls) -> StateMigrationError:
        return cls(
            "only one consolidated state database exists; manual recovery is required"
        )

    @classmethod
    def integrity_failed(cls, path: Path) -> StateMigrationError:
        return cls(f"SQLite integrity check failed: {path}")

    @classmethod
    def namespace_mismatch(
        cls,
        path: Path,
        actual: set[str],
        expected: frozenset[str],
    ) -> StateMigrationError:
        return cls(
            f"consolidated state database has unexpected migration namespaces: "
            f"{path} (actual={sorted(actual)}, expected={sorted(expected)})"
        )


@dataclass(frozen=True, slots=True)
class LegacySource:
    relative_path: str
    target: StateTarget | None
    tables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationResult:
    applied: bool
    already_migrated: bool
    backup_path: Path | None
    migrated_rows: dict[str, int]
    legacy_files: tuple[Path, ...]


LEGACY_SOURCES = (
    LegacySource("seer/player_bindings.sqlite", "qq", ("player_bindings",)),
    LegacySource(
        "seer/player_query_limits.sqlite",
        "qq",
        ("player_query_usage",),
    ),
    LegacySource(
        "messaging/push_unsubscriptions.sqlite",
        "qq",
        (
            "push_unsubscriptions",
            "push_time_preferences",
            "push_daily_hints",
        ),
    ),
    LegacySource(
        "bilibili_monitor/push_preferences.sqlite",
        "qq",
        ("bili_push_preferences",),
    ),
    LegacySource(
        "seer/rank_display_limits.sqlite",
        "qq",
        ("group_rank_display_limits",),
    ),
    LegacySource(
        "seer/team_resource_subscriptions.sqlite",
        "qq",
        (
            "team_resource_subscriptions",
            "team_resource_subscription_prompts",
            "team_resource_private_subscriptions",
        ),
    ),
    LegacySource(
        "activity_reminder/sent.sqlite",
        "runtime",
        ("sent_activity_reminders",),
    ),
    LegacySource(
        "team_audit_welcome/pending.sqlite",
        "runtime",
        ("pending_team_audit_reminders",),
    ),
    LegacySource(
        "seer/lucky_skin_window.sqlite",
        "runtime",
        ("lucky_skin_window_daily_cache",),
    ),
    LegacySource("messaging/private_push_unsubscriptions.sqlite", None),
    LegacySource("messaging/reply_limits.sqlite", None),
    LegacySource("message_actions/reply_limits.sqlite", None),
    LegacySource("seer/achievement_history.sqlite", None),
)

_SKIN_WINDOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS lucky_skin_window_daily_cache (
    day TEXT PRIMARY KEY,
    skin_ids_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
)
"""


def migrate_state_databases(  # noqa: PLR0913
    *,
    data_root: Path,
    qq_state_path: Path | None = None,
    runtime_state_path: Path | None = None,
    backup_root: Path | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> MigrationResult:
    data_root = data_root.resolve()
    qq_state = _resolve_target(
        data_root,
        qq_state_path,
        "state/qq_state.sqlite",
    )
    runtime_state = _resolve_target(
        data_root,
        runtime_state_path,
        "state/runtime_state.sqlite",
    )
    if qq_state == runtime_state:
        raise StateMigrationError.same_target()

    sources = tuple(
        (source, data_root / source.relative_path)
        for source in LEGACY_SOURCES
        if (data_root / source.relative_path).is_file()
    )
    targets_exist = qq_state.exists() or runtime_state.exists()
    if targets_exist:
        _validate_existing_targets(qq_state, runtime_state)
        if sources:
            raise StateMigrationError.targets_with_legacy()
        return MigrationResult(
            applied=False,
            already_migrated=True,
            backup_path=None,
            migrated_rows=_state_row_counts(qq_state, runtime_state),
            legacy_files=tuple(path for _, path in sources),
        )

    preview_counts = _legacy_row_counts(sources)
    if not apply:
        return MigrationResult(
            applied=False,
            already_migrated=False,
            backup_path=None,
            migrated_rows=preview_counts,
            legacy_files=tuple(path for _, path in sources),
        )

    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    backup_base = (backup_root or data_root / "state-migration-backups").resolve()
    backup_path = _unique_backup_path(backup_base, timestamp)
    _backup_legacy_sources(data_root, sources, backup_path)

    temp_qq = _temporary_target(qq_state)
    temp_runtime = _temporary_target(runtime_state)
    installed_targets: list[Path] = []
    try:
        _initialize_state_databases(temp_qq, temp_runtime)
        migrated_rows = _copy_legacy_data(
            sources,
            qq_state=temp_qq,
            runtime_state=temp_runtime,
        )
        _validate_migrated_state(temp_qq, temp_runtime, sources)
        _prepare_for_atomic_replace(temp_qq)
        _prepare_for_atomic_replace(temp_runtime)
        _write_manifest(
            backup_path,
            data_root=data_root,
            qq_state=qq_state,
            runtime_state=runtime_state,
            sources=sources,
            migrated_rows=migrated_rows,
            created_at=now or datetime.now(timezone.utc),
        )
        qq_state.parent.mkdir(parents=True, exist_ok=True)
        runtime_state.parent.mkdir(parents=True, exist_ok=True)
        temp_qq.replace(qq_state)
        installed_targets.append(qq_state)
        temp_runtime.replace(runtime_state)
        installed_targets.append(runtime_state)
        _archive_active_legacy_files(data_root, sources)
    except BaseException:
        _remove_sqlite_files(temp_qq)
        _remove_sqlite_files(temp_runtime)
        for installed in installed_targets:
            _remove_sqlite_files(installed)
        raise
    return MigrationResult(
        applied=True,
        already_migrated=False,
        backup_path=backup_path,
        migrated_rows=migrated_rows,
        legacy_files=tuple(path for _, path in sources),
    )


def _resolve_target(
    data_root: Path,
    configured: Path | None,
    default_relative: str,
) -> Path:
    path = configured or Path(default_relative)
    return path.resolve() if path.is_absolute() else (data_root / path).resolve()


def _unique_backup_path(root: Path, timestamp: str) -> Path:
    candidate = root / timestamp
    if not candidate.exists():
        return candidate
    return root / f"{timestamp}-{uuid4().hex[:8]}"


def _temporary_target(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.with_name(f".{target.name}.migrating-{uuid4().hex}")


def _initialize_state_databases(qq_state: Path, runtime_state: Path) -> None:
    SqlitePlayerBindingStore(qq_state).get(0)
    SqlitePlayerQueryLimitStore(qq_state).status(
        local_date=datetime.now(timezone.utc).date(),
        qq_user_id=0,
        scope="bound_default",
        player_id=0,
        action_key="migration",
        limit=1,
    )
    PushUnsubscribeStore(qq_state).preference_targets()
    SqliteBiliPushPreferenceStore(qq_state).get_mode("private", 0, 0)
    SqliteRankDisplayStore(qq_state).get(0)
    TeamResourceSubscriptionStore(qq_state).list_all()

    ActivitySentStore(runtime_state).filter_unsent([])
    SqliteTeamAuditReminderStore(runtime_state).list_all()
    with SqliteDatabase(
        runtime_state,
        migrations=(SqliteMigration(1, (_SKIN_WINDOW_SCHEMA,)),),
        migration_namespace="skin_window",
    ).connect():
        pass


def _backup_legacy_sources(
    data_root: Path,
    sources: tuple[tuple[LegacySource, Path], ...],
    backup_path: Path,
) -> None:
    backup_path.mkdir(parents=True, exist_ok=False)
    for _, source_path in sources:
        relative = source_path.relative_to(data_root)
        destination = backup_path / "legacy" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{source_path}{suffix}")
            if sidecar.is_file():
                shutil.copy2(sidecar, Path(f"{destination}{suffix}"))


def _copy_legacy_data(
    sources: tuple[tuple[LegacySource, Path], ...],
    *,
    qq_state: Path,
    runtime_state: Path,
) -> dict[str, int]:
    copied: dict[str, int] = {}
    targets = {"qq": qq_state, "runtime": runtime_state}
    for source, source_path in sources:
        if source.target is None:
            continue
        target_path = targets[source.target]
        with open_sqlite_connection(target_path) as target:
            target.execute("ATTACH DATABASE ? AS legacy", (str(source_path),))
            try:
                for table in source.tables:
                    if not _table_exists(target, "legacy", table):
                        continue
                    copied[table] = _copy_table(target, table)
                target.commit()
            finally:
                target.execute("DETACH DATABASE legacy")

    legacy_private = next(
        (
            path
            for source, path in sources
            if source.relative_path
            == "messaging/private_push_unsubscriptions.sqlite"
        ),
        None,
    )
    if legacy_private is not None:
        copied["private_push_unsubscriptions"] = _copy_private_unsubscriptions(
            qq_state,
            legacy_private,
        )
    return copied


def _copy_table(connection: sqlite3.Connection, table: str) -> int:
    table_sql = quote_sqlite_identifier(table)
    source_columns = _table_columns(connection, "legacy", table)
    target_columns = _table_columns(connection, "main", table)
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        raise StateMigrationError.incompatible_table(table)
    columns_sql = ", ".join(quote_sqlite_identifier(column) for column in columns)
    source_count = int(
        connection.execute(f"SELECT COUNT(*) FROM legacy.{table_sql}").fetchone()[0]
    )
    connection.execute(
        f"INSERT INTO main.{table_sql} ({columns_sql}) "
        f"SELECT {columns_sql} FROM legacy.{table_sql}"
    )
    return source_count


def _copy_private_unsubscriptions(target_path: Path, source_path: Path) -> int:
    with open_sqlite_connection(target_path) as target:
        target.execute("ATTACH DATABASE ? AS legacy_private", (str(source_path),))
        try:
            if not _table_exists(
                target,
                "legacy_private",
                "private_push_unsubscriptions",
            ):
                return 0
            before = int(
                target.execute(
                    "SELECT COUNT(*) FROM push_unsubscriptions"
                ).fetchone()[0]
            )
            target.execute(
                """
                INSERT OR IGNORE INTO push_unsubscriptions (
                    target_type, target_id, subscription_key, feature, created_at
                )
                SELECT 'private', user_id, schedule_key, feature, created_at
                FROM legacy_private.private_push_unsubscriptions
                """
            )
            target.commit()
            after = int(
                target.execute(
                    "SELECT COUNT(*) FROM push_unsubscriptions"
                ).fetchone()[0]
            )
            return after - before
        finally:
            target.execute("DETACH DATABASE legacy_private")


def _table_exists(
    connection: sqlite3.Connection,
    schema: str,
    table: str,
) -> bool:
    row = connection.execute(
        f"SELECT 1 FROM {quote_sqlite_identifier(schema)}.sqlite_master "
        "WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(
    connection: sqlite3.Connection,
    schema: str,
    table: str,
) -> list[str]:
    schema_sql = quote_sqlite_identifier(schema)
    table_sql = quote_sqlite_identifier(table)
    return [
        str(row[1])
        for row in connection.execute(
            f"PRAGMA {schema_sql}.table_info({table_sql})"
        ).fetchall()
    ]


def _legacy_row_counts(
    sources: tuple[tuple[LegacySource, Path], ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source, path in sources:
        if not source.tables:
            continue
        with _read_only_connection(path) as connection:
            for table in source.tables:
                if not _table_exists(connection, "main", table):
                    continue
                table_sql = quote_sqlite_identifier(table)
                counts[table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[
                        0
                    ]
                )
    legacy_private = next(
        (
            path
            for source, path in sources
            if source.relative_path
            == "messaging/private_push_unsubscriptions.sqlite"
        ),
        None,
    )
    if legacy_private is not None:
        with _read_only_connection(legacy_private) as connection:
            if _table_exists(
                connection,
                "main",
                "private_push_unsubscriptions",
            ):
                counts["private_push_unsubscriptions"] = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM private_push_unsubscriptions"
                    ).fetchone()[0]
                )
    return counts


def _expected_target_row_counts(
    sources: tuple[tuple[LegacySource, Path], ...],
) -> dict[str, int]:
    counts = _legacy_row_counts(sources)
    counts.pop("private_push_unsubscriptions", None)

    push_keys: set[tuple[str, int, str]] = set()
    for source, path in sources:
        if source.relative_path == "messaging/push_unsubscriptions.sqlite":
            with _read_only_connection(path) as connection:
                if _table_exists(connection, "main", "push_unsubscriptions"):
                    rows = connection.execute(
                        "SELECT target_type, target_id, subscription_key "
                        "FROM push_unsubscriptions"
                    )
                    push_keys.update(
                        (str(target_type), int(target_id), str(subscription_key))
                        for target_type, target_id, subscription_key in rows
                    )
        elif (
            source.relative_path
            == "messaging/private_push_unsubscriptions.sqlite"
        ):
            with _read_only_connection(path) as connection:
                if _table_exists(
                    connection,
                    "main",
                    "private_push_unsubscriptions",
                ):
                    push_keys.update(
                        ("private", int(user_id), str(schedule_key))
                        for user_id, schedule_key in connection.execute(
                            "SELECT user_id, schedule_key "
                            "FROM private_push_unsubscriptions"
                        )
                    )
    if push_keys:
        counts["push_unsubscriptions"] = len(push_keys)
    return counts


def _state_row_counts(qq_state: Path, runtime_state: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (qq_state, runtime_state):
        if not path.is_file():
            continue
        with _read_only_connection(path) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name != 'ironsbot_schema_migrations'"
            ).fetchall()
            for (table,) in tables:
                table_text = str(table)
                table_sql = quote_sqlite_identifier(table_text)
                counts[table_text] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[
                        0
                    ]
                )
    return counts


def _validate_migrated_state(
    qq_state: Path,
    runtime_state: Path,
    sources: tuple[tuple[LegacySource, Path], ...],
) -> None:
    expected = _expected_target_row_counts(sources)
    actual = _state_row_counts(qq_state, runtime_state)
    for table, expected_count in expected.items():
        actual_count = actual.get(table, 0)
        if actual_count != expected_count:
            raise StateMigrationError.row_count_mismatch(
                table,
                actual_count,
                expected_count,
            )
    _validate_integrity(qq_state)
    _validate_integrity(runtime_state)
    _validate_namespaces(qq_state, QQ_STATE_NAMESPACES)
    _validate_namespaces(runtime_state, RUNTIME_STATE_NAMESPACES)


def _validate_existing_targets(qq_state: Path, runtime_state: Path) -> None:
    if not qq_state.is_file() or not runtime_state.is_file():
        raise StateMigrationError.partial_targets()
    _validate_integrity(qq_state)
    _validate_integrity(runtime_state)
    _validate_namespaces(qq_state, QQ_STATE_NAMESPACES)
    _validate_namespaces(runtime_state, RUNTIME_STATE_NAMESPACES)


def _validate_namespaces(path: Path, expected: frozenset[str]) -> None:
    with _read_only_connection(path) as connection:
        if not _table_exists(
            connection,
            "main",
            "ironsbot_schema_migrations",
        ):
            raise StateMigrationError.namespace_mismatch(path, set(), expected)
        actual = {
            str(row[0])
            for row in connection.execute(
                "SELECT namespace FROM ironsbot_schema_migrations"
            )
        }
    if actual != expected:
        raise StateMigrationError.namespace_mismatch(path, actual, expected)


def _validate_integrity(path: Path) -> None:
    with _read_only_connection(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise StateMigrationError.integrity_failed(path)


def _prepare_for_atomic_replace(path: Path) -> None:
    with open_sqlite_connection(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or str(result[0]).lower() != "ok":
        raise StateMigrationError.integrity_failed(path)


def _archive_active_legacy_files(
    data_root: Path,
    sources: tuple[tuple[LegacySource, Path], ...],
) -> None:
    for _, source_path in sources:
        if source_path.is_relative_to(data_root):
            _remove_sqlite_files(source_path)


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    return open_sqlite_connection(path, read_only=True)


def _write_manifest(  # noqa: PLR0913
    backup_path: Path,
    *,
    data_root: Path,
    qq_state: Path,
    runtime_state: Path,
    sources: tuple[tuple[LegacySource, Path], ...],
    migrated_rows: dict[str, int],
    created_at: datetime,
) -> None:
    manifest = {
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "qq_state": str(qq_state),
        "runtime_state": str(runtime_state),
        "legacy_files": [source.relative_path for source, _ in sources],
        "migrated_rows": migrated_rows,
    }
    (backup_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _format_result(result: MigrationResult) -> str:
    lines = []
    if result.already_migrated:
        lines.append("State databases are already consolidated.")
    elif result.applied:
        lines.append("State database migration completed.")
    else:
        lines.append("Dry run only; no files were changed.")
    lines.append(f"Legacy files found: {len(result.legacy_files)}")
    lines.extend(f"- {path}" for path in result.legacy_files)
    if result.migrated_rows:
        lines.append("Rows:")
        lines.extend(
            f"- {table}: {count}"
            for table, count in sorted(result.migrated_rows.items())
        )
    if result.backup_path is not None:
        lines.append(f"Backup: {result.backup_path}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consolidate legacy IronsBot state SQLite files.",
    )
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--qq-state", type=Path)
    parser.add_argument("--runtime-state", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the migration. Without this flag only a dry run is performed.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = migrate_state_databases(
            data_root=args.data_root,
            qq_state_path=args.qq_state,
            runtime_state_path=args.runtime_state,
            backup_root=args.backup_root,
            apply=args.apply,
        )
    except (OSError, sqlite3.Error, StateMigrationError) as error:
        sys.stderr.write(f"State migration failed: {error}\n")
        return 1
    sys.stdout.write(f"{_format_result(result)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
