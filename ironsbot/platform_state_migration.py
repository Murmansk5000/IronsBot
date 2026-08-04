# SPDX-License-Identifier: MIT
"""Offline, atomic migration of persisted delivery-platform identities."""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ironsbot.integrations.storage.platform_state_schema import (
    AI_IDENTITY_TABLES,
    QQ_IDENTITY_TABLES,
    RUNTIME_IDENTITY_TABLES,
    PlatformStateDataError,
    copy_ai_memory,
    copy_passthrough_tables,
    copy_qq_state,
    copy_runtime_state,
    create_ai_memory_schema,
    create_qq_state_schema,
    create_runtime_state_schema,
    source_table_counts,
    table_exists,
)
from ironsbot.integrations.storage.sqlite import open_sqlite_connection

_VERSION = 1
_MARKER_TABLE = "ironsbot_platform_identity_migration"
_META_TABLE = "ironsbot_schema_migrations"
_QQ_NAMESPACES = frozenset(
    {
        "bilibili_preferences",
        "lucky_skin_watch",
        "player_bindings",
        "player_query_limits",
        "push_subscriptions",
        "rank_display",
        "team_resources",
    }
)
_RUNTIME_NAMESPACES = frozenset({"activity_reminder", "skin_window", "team_audit"})
_QQ_IDENTITY_NAMESPACES = _QQ_NAMESPACES
_RUNTIME_IDENTITY_NAMESPACES = frozenset({"team_audit"})


class PlatformStateMigrationError(RuntimeError):
    """Raised when a platform-state migration cannot complete safely."""

    @classmethod
    def partial_target(cls) -> PlatformStateMigrationError:
        return cls("platform identity migration is only partially applied")

    @classmethod
    def target_path_conflict(cls) -> PlatformStateMigrationError:
        return cls("platform identity target paths must be distinct")

    @classmethod
    def integrity_failed(cls, path: Path) -> PlatformStateMigrationError:
        return cls(f"SQLite integrity check failed: {path}")

    @classmethod
    def row_count_mismatch(
        cls,
        table: str,
        actual: int,
        expected: int,
    ) -> PlatformStateMigrationError:
        return cls(f"row count mismatch for {table}: {actual} != {expected}")


@dataclass(frozen=True, slots=True)
class PlatformStateMigrationResult:
    applied: bool
    already_migrated: bool
    backup_path: Path | None
    migrated_rows: dict[str, int]


@dataclass(frozen=True, slots=True)
class PlatformStatePaths:
    data_root: Path
    qq_state: Path
    runtime_state: Path
    ai_memory: Path

    @property
    def targets(self) -> tuple[Path, Path, Path]:
        return (self.qq_state, self.runtime_state, self.ai_memory)


def format_platform_state_migration_result(
    result: PlatformStateMigrationResult,
) -> str:
    """Render a human-readable result for the offline CLI."""

    lines: list[str] = []
    if result.already_migrated:
        lines.append("Platform identities are already migrated.")
    elif result.applied:
        lines.append("Platform identity migration completed.")
    else:
        lines.append("Dry run only; no files were changed.")
    if result.migrated_rows:
        lines.append("Rows:")
        lines.extend(
            f"- {table}: {count}"
            for table, count in sorted(result.migrated_rows.items())
        )
    if result.backup_path is not None:
        lines.append(f"Backup: {result.backup_path}")
    return "\n".join(lines)


def migrate_platform_state_identities(  # noqa: PLR0913
    *,
    data_root: Path,
    qq_state_path: Path | None = None,
    runtime_state_path: Path | None = None,
    ai_memory_path: Path | None = None,
    backup_root: Path | None = None,
    apply: bool = False,
    now: datetime | None = None,
) -> PlatformStateMigrationResult:
    """Convert OneBot integer identity fields while the application is stopped."""

    paths = platform_state_paths(
        data_root,
        qq_state_path=qq_state_path,
        runtime_state_path=runtime_state_path,
        ai_memory_path=ai_memory_path,
    )
    migrated = tuple(_is_migrated(path) for path in paths.targets)
    if all(migrated):
        return PlatformStateMigrationResult(
            applied=False,
            already_migrated=True,
            backup_path=None,
            migrated_rows=_target_row_counts(paths),
        )
    if any(migrated):
        raise PlatformStateMigrationError.partial_target()

    expected = _source_row_counts(paths)
    _validate_in_memory(paths, expected)
    if not apply:
        return PlatformStateMigrationResult(
            applied=False,
            already_migrated=False,
            backup_path=None,
            migrated_rows=expected,
        )

    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    backup_base = (
        backup_root or paths.data_root / "platform-identity-migration-backups"
    ).resolve()
    backup = _backup_sources(
        paths,
        _unique_backup_path(
            backup_base,
            timestamp,
        ),
    )
    temporary = (
        _temporary_path(paths.qq_state),
        _temporary_path(paths.runtime_state),
        _temporary_path(paths.ai_memory),
    )
    installed: list[tuple[Path, bool]] = []
    try:
        _build_targets(paths, temporary)
        _validate_target_files(temporary, expected)
        for source, target in zip(paths.targets, temporary, strict=True):
            existed = source.is_file()
            target.replace(source)
            _remove_sidecars(source)
            installed.append((source, existed))
    except BaseException:
        _restore_sources(installed, backup)
        for path in temporary:
            _remove_sqlite_bundle(path)
        raise
    return PlatformStateMigrationResult(
        applied=True,
        already_migrated=False,
        backup_path=backup.root,
        migrated_rows=expected,
    )


def platform_state_paths(
    data_root: Path,
    *,
    qq_state_path: Path | None = None,
    runtime_state_path: Path | None = None,
    ai_memory_path: Path | None = None,
) -> PlatformStatePaths:
    root = data_root.resolve()
    paths = PlatformStatePaths(
        data_root=root,
        qq_state=_resolve_path(root, qq_state_path, "state/qq_state.sqlite"),
        runtime_state=_resolve_path(
            root,
            runtime_state_path,
            "state/runtime_state.sqlite",
        ),
        ai_memory=_resolve_path(root, ai_memory_path, "ai_chat/memory.sqlite"),
    )
    if len(set(paths.targets)) != len(paths.targets):
        raise PlatformStateMigrationError.target_path_conflict()
    return paths


def _resolve_path(root: Path, configured: Path | None, default: str) -> Path:
    path = configured or Path(default)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validate_in_memory(paths: PlatformStatePaths, expected: dict[str, int]) -> None:
    temporary = (
        sqlite3.connect(":memory:"),
        sqlite3.connect(":memory:"),
        sqlite3.connect(":memory:"),
    )
    try:
        for connection in temporary:
            connection.row_factory = sqlite3.Row
        _build_connections(paths, temporary)
        _validate_target_counts(temporary, expected)
    except (PlatformStateDataError, sqlite3.Error) as error:
        raise PlatformStateMigrationError(str(error)) from error
    finally:
        for connection in temporary:
            connection.close()


def _build_targets(
    paths: PlatformStatePaths,
    temporary: tuple[Path, Path, Path],
) -> None:
    connections = (
        open_sqlite_connection(temporary[0]),
        open_sqlite_connection(temporary[1]),
        open_sqlite_connection(temporary[2]),
    )
    try:
        for connection in connections:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
        _build_connections(paths, connections)
    except BaseException:
        for connection in connections:
            connection.rollback()
        raise
    else:
        for connection in connections:
            connection.commit()
    finally:
        for connection in connections:
            connection.close()


def _build_connections(
    paths: PlatformStatePaths,
    connections: tuple[sqlite3.Connection, sqlite3.Connection, sqlite3.Connection],
) -> None:
    qq_state, runtime_state, ai_memory = connections
    _create_meta(qq_state)
    create_qq_state_schema(qq_state)
    copy_qq_state(paths.qq_state, qq_state)
    copy_passthrough_tables(
        paths.qq_state,
        qq_state,
        excluded=QQ_IDENTITY_TABLES | {_MARKER_TABLE, _META_TABLE},
    )
    _copy_namespaces(
        paths.qq_state,
        qq_state,
        _QQ_NAMESPACES,
        _QQ_IDENTITY_NAMESPACES,
    )
    _mark_migrated(qq_state)

    _create_meta(runtime_state)
    create_runtime_state_schema(runtime_state)
    copy_runtime_state(paths.runtime_state, runtime_state)
    copy_passthrough_tables(
        paths.runtime_state,
        runtime_state,
        excluded=RUNTIME_IDENTITY_TABLES | {_MARKER_TABLE, _META_TABLE},
    )
    _copy_namespaces(
        paths.runtime_state,
        runtime_state,
        _RUNTIME_NAMESPACES,
        _RUNTIME_IDENTITY_NAMESPACES,
    )
    _mark_migrated(runtime_state)

    create_ai_memory_schema(ai_memory)
    copy_ai_memory(paths.ai_memory, ai_memory)
    copy_passthrough_tables(
        paths.ai_memory,
        ai_memory,
        excluded=AI_IDENTITY_TABLES | {_MARKER_TABLE},
    )
    _mark_migrated(ai_memory)


def _create_meta(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE ironsbot_schema_migrations (
            namespace TEXT PRIMARY KEY,
            version INTEGER NOT NULL CHECK (version >= 0),
            updated_at TEXT NOT NULL
        )
        """
    )


def _copy_namespaces(
    source: Path,
    target: sqlite3.Connection,
    namespaces: frozenset[str],
    identity_namespaces: frozenset[str],
) -> None:
    source_versions = _namespace_versions(source)
    timestamp = datetime.now(timezone.utc).isoformat()
    for namespace in namespaces:
        version = (
            1
            if namespace in identity_namespaces
            else source_versions.get(namespace, 1)
        )
        target.execute(
            "INSERT INTO ironsbot_schema_migrations VALUES (?, ?, ?)",
            (namespace, version, timestamp),
        )


def _namespace_versions(source: Path) -> dict[str, int]:
    if not table_exists(source, _META_TABLE):
        return {}
    with _read(source) as connection:
        return {
            str(row["namespace"]): int(row["version"])
            for row in connection.execute(
                "SELECT namespace, version FROM ironsbot_schema_migrations"
            )
        }


def _mark_migrated(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE {_MARKER_TABLE} (
            version INTEGER NOT NULL,
            migrated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"INSERT INTO {_MARKER_TABLE} VALUES (?, ?)",
        (_VERSION, datetime.now(timezone.utc).isoformat()),
    )


def _source_row_counts(paths: PlatformStatePaths) -> dict[str, int]:
    counts = source_table_counts(paths.qq_state, QQ_IDENTITY_TABLES)
    counts.update(source_table_counts(paths.runtime_state, RUNTIME_IDENTITY_TABLES))
    counts.update(source_table_counts(paths.ai_memory, AI_IDENTITY_TABLES))
    return counts


def _target_row_counts(paths: PlatformStatePaths) -> dict[str, int]:
    return _source_row_counts(paths)


def _validate_target_files(
    paths: tuple[Path, Path, Path],
    expected: dict[str, int],
) -> None:
    for path in paths:
        _prepare_target(path)
    connections = (_read(paths[0]), _read(paths[1]), _read(paths[2]))
    try:
        _validate_target_counts(connections, expected)
    finally:
        for connection in connections:
            connection.close()


def _validate_target_counts(
    connections: tuple[sqlite3.Connection, sqlite3.Connection, sqlite3.Connection],
    expected: dict[str, int],
) -> None:
    qq_state, runtime_state, ai_memory = connections
    actual = {
        **_connection_counts(qq_state, QQ_IDENTITY_TABLES),
        **_connection_counts(runtime_state, RUNTIME_IDENTITY_TABLES),
        **_connection_counts(ai_memory, AI_IDENTITY_TABLES),
    }
    for table, expected_count in expected.items():
        actual_count = actual.get(table, 0)
        if actual_count != expected_count:
            raise PlatformStateMigrationError.row_count_mismatch(
                table,
                actual_count,
                expected_count,
            )


def _connection_counts(
    connection: sqlite3.Connection,
    tables: frozenset[str],
) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    }


def _is_migrated(path: Path) -> bool:
    if not table_exists(path, _MARKER_TABLE):
        return False
    with _read(path) as connection:
        row = connection.execute(f"SELECT version FROM {_MARKER_TABLE}").fetchone()
    return row is not None and int(row["version"]) == _VERSION


def _prepare_target(path: Path) -> None:
    with open_sqlite_connection(path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode=DELETE")
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
    if foreign_key_violations:
        raise PlatformStateMigrationError.integrity_failed(path)
    _validate_integrity(path)


def _validate_integrity(path: Path) -> None:
    with _read(path) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None or str(row[0]).lower() != "ok":
        raise PlatformStateMigrationError.integrity_failed(path)


@dataclass(frozen=True, slots=True)
class _Backup:
    root: Path
    files: dict[Path, Path]


def _backup_sources(paths: PlatformStatePaths, root: Path) -> _Backup:
    root.mkdir(parents=True, exist_ok=False)
    files: dict[Path, Path] = {}
    for label, path in (
        ("qq_state", paths.qq_state),
        ("runtime_state", paths.runtime_state),
        ("ai_memory", paths.ai_memory),
    ):
        if not path.is_file():
            continue
        relative = _backup_relative(paths.data_root, label, path)
        destination = root / relative
        _copy_sqlite_bundle(path, destination)
        files[path] = destination
    (root / "manifest.json").write_text(
        json.dumps(
            {
                str(path): str(destination.relative_to(root))
                for path, destination in files.items()
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return _Backup(root, files)


def _backup_relative(data_root: Path, label: str, path: Path) -> Path:
    if path.is_relative_to(data_root):
        return path.relative_to(data_root)
    return Path("external") / label / path.name


def _copy_sqlite_bundle(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.is_file():
            shutil.copy2(sidecar, Path(f"{destination}{suffix}"))


def _restore_sources(installed: list[tuple[Path, bool]], backup: _Backup) -> None:
    for source, existed in installed:
        _remove_sqlite_bundle(source)
        if existed:
            _copy_sqlite_bundle(backup.files[source], source)


def _temporary_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.with_name(f".{path.name}.platform-migrating-{uuid4().hex}")


def _unique_backup_path(root: Path, timestamp: str) -> Path:
    candidate = root / timestamp
    if not candidate.exists():
        return candidate
    return root / f"{timestamp}-{uuid4().hex[:8]}"


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _remove_sqlite_bundle(path: Path) -> None:
    path.unlink(missing_ok=True)
    _remove_sidecars(path)


def _read(path: Path) -> sqlite3.Connection:
    connection = open_sqlite_connection(path, read_only=True)
    connection.row_factory = sqlite3.Row
    return connection
