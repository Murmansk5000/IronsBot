# SPDX-License-Identifier: MIT
"""Filesystem operations used by offline SQLite state migrations."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


@dataclass(frozen=True, slots=True)
class SqliteBundleChange:
    target: Path
    replacement: Path | None = None
    backup: Path | None = None


class SqliteBundleInstallError(OSError):
    """An invalid offline install plan or an incomplete compensating rollback."""


def _bundle_paths(path: Path) -> tuple[Path, ...]:
    return (path, *(Path(f"{path}{suffix}") for suffix in _SIDECAR_SUFFIXES))


def copy_sqlite_bundle(source: Path, destination: Path) -> None:
    """Copy an offline database with every present SQLite sidecar."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    for source_file, target_file in zip(
        _bundle_paths(source)[1:],
        _bundle_paths(destination)[1:],
        strict=True,
    ):
        if source_file.is_file():
            shutil.copy2(source_file, target_file)


def apply_sqlite_bundle_changes(changes: tuple[SqliteBundleChange, ...]) -> None:
    """Install validated offline files, compensating for catchable failures.

    This is not a cross-file transaction against process death or power loss.
    Callers must stop the application and keep the supplied backups.
    """
    _validate_changes(changes)
    touched: list[SqliteBundleChange] = []
    try:
        for change in changes:
            touched.append(change)
            if change.replacement is None:
                remove_sqlite_bundle(change.target)
            else:
                change.target.parent.mkdir(parents=True, exist_ok=True)
                _replace_bundle(change.replacement, change.target)
    except BaseException as error:
        failures: list[str] = []
        for change in reversed(touched):
            try:
                _restore_change(change)
            except BaseException as restore_error:  # noqa: BLE001, PERF203 - restore every target
                failures.append(
                    f"{change.target} (backup={change.backup}): {restore_error}"
                )
        if failures:
            message = "SQLite rollback incomplete; keep backups: " + "; ".join(failures)
            raise SqliteBundleInstallError(message) from error
        raise


def _validate_changes(changes: tuple[SqliteBundleChange, ...]) -> None:
    targets: set[Path] = set()
    sources: set[Path] = set()
    for change in changes:
        _validate_original(change)
        bundle = {path.resolve() for path in _bundle_paths(change.target)}
        if targets.intersection(bundle):
            message = f"overlapping SQLite target: {change.target}"
            raise SqliteBundleInstallError(message)
        targets.update(bundle)
        for source in (change.replacement, change.backup):
            if source is not None:
                if not source.is_file():
                    raise SqliteBundleInstallError(str(source))
                source_bundle = {path.resolve() for path in _bundle_paths(source)}
                if sources.intersection(source_bundle):
                    message = f"overlapping SQLite source: {source}"
                    raise SqliteBundleInstallError(message)
                sources.update(source_bundle)
    if targets.intersection(sources):
        message = "SQLite replacement/backup must not overlap a target"
        raise SqliteBundleInstallError(message)


def _validate_original(change: SqliteBundleChange) -> None:
    if change.target.exists() and not change.target.is_file():
        raise SqliteBundleInstallError(str(change.target))
    if change.target.is_file() != (change.backup is not None):
        message = f"SQLite target requires original backup: {change.target}"
        raise SqliteBundleInstallError(message)
    if not change.target.is_file() and any(
        path.exists() for path in _bundle_paths(change.target)[1:]
    ):
        message = f"orphan SQLite sidecar: {change.target}"
        raise SqliteBundleInstallError(message)


def _replace_bundle(source: Path, target: Path) -> None:
    for path in _bundle_paths(target)[1:]:
        path.unlink(missing_ok=True)
    source.replace(target)
    for source_file, target_file in zip(
        _bundle_paths(source)[1:],
        _bundle_paths(target)[1:],
        strict=True,
    ):
        if source_file.exists():
            source_file.replace(target_file)


def _restore_change(change: SqliteBundleChange) -> None:
    if change.backup is None:
        remove_sqlite_bundle(change.target)
        return
    staging = change.target.with_name(f".{change.target.name}.restore-{uuid4().hex}")
    try:
        copy_sqlite_bundle(change.backup, staging)
        _replace_bundle(staging, change.target)
    finally:
        cleanup_sqlite_bundles((staging,))


def cleanup_sqlite_bundles(paths: Iterable[Path]) -> None:
    """Best-effort temporary cleanup without masking install/restore failures."""
    for path in paths:
        try:
            remove_sqlite_bundle(path)
        except OSError:  # noqa: PERF203 - try to clean every temporary bundle
            logger.exception("Failed to clean temporary SQLite bundle: %s", path)


def remove_sqlite_bundle(path: Path) -> None:
    """Remove a SQLite database and its optional WAL sidecars."""
    for candidate in _bundle_paths(path):
        candidate.unlink(missing_ok=True)
