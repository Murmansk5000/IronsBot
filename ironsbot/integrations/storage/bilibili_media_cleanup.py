# SPDX-License-Identifier: MIT
"""Reference-aware, fail-closed collection within a dedicated media directory."""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ironsbot.services.bilibili.delivery_ledger import MediaCleanupResult

if TYPE_CHECKING:
    import sqlite3

ORPHAN_GRACE_SECONDS = 3600
SHA256_LENGTH = 64
TEMP_PREFIX = ".media-"
TEMP_RANDOM_LENGTH = 8


def _digests(payload: str) -> set[str]:
    entries = json.loads(payload)
    if not isinstance(entries, list):
        message = "Invalid media manifest"
        raise TypeError(message)
    result = set()
    for entry in entries:
        if not isinstance(entry, dict):
            message = "Invalid media entry"
            raise TypeError(message)
        if "url" in entry:
            if not isinstance(entry["url"], str):
                message = "Invalid remote media metadata"
                raise TypeError(message)
            continue
        digest = entry.get("sha256")
        if not _is_digest(digest):
            message = "Invalid media digest"
            raise ValueError(message)
        if not all(
            isinstance(entry.get(key), str) for key in ("content_type", "filename")
        ):
            message = "Invalid binary media metadata"
            raise ValueError(message)
        result.add(digest)
    return result


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(char in "0123456789abcdef" for char in value)
    )


def _is_temporary(name: str) -> bool:
    suffix = name.removeprefix(TEMP_PREFIX)
    return (
        name.startswith(TEMP_PREFIX)
        and len(suffix) == TEMP_RANDOM_LENGTH
        and all(char in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in suffix)
    )


def _message_digests(payload: str | None) -> set[str]:
    if payload is None:
        return set()
    entries = json.loads(payload)
    if not isinstance(entries, list):
        message = "Invalid message manifest"
        raise TypeError(message)
    result = set()
    for entry in entries:
        if not isinstance(entry, dict):
            message = "Invalid message entry"
            raise TypeError(message)
        if "media" in entry:
            result.update(_digests(entry["media"]))
        elif "text" in entry and not isinstance(entry["text"], str):
            message = "Invalid text snapshot"
            raise ValueError(message)
        elif "actor" in entry and not isinstance(entry["actor"], dict):
            message = "Invalid mention snapshot"
            raise ValueError(message)
        elif "text" not in entry and "actor" not in entry:
            message = "Unknown message entry"
            raise ValueError(message)
    return result


def _references(db: sqlite3.Connection, now: float, retention: int) -> set[str]:
    sending = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT dynamic_id FROM stages WHERE state='sending'"
        )
    }
    protected = set(sending)
    for dynamic_id, created, payload in db.execute(
        "SELECT id,created,payload FROM deliveries"
    ):
        published = json.loads(payload)["pub_ts"]
        if (
            isinstance(published, bool)
            or not isinstance(published, (int, float))
            or not math.isfinite(published)
            or not math.isfinite(created)
        ):
            message = "Invalid delivery timestamp"
            raise ValueError(message)
        if created + retention >= now and published + retention >= now:
            protected.add(dynamic_id)
    result = set()
    for table, decode in (
        ("media_manifests", _digests),
        ("text_manifests", _message_digests),
        ("unit_messages", _message_digests),
    ):
        for dynamic_id, payload in db.execute(
            f"SELECT dynamic_id,payload FROM {table}"
        ):
            references = decode(payload)
            if dynamic_id in protected:
                result.update(references)
    return result


def _regular(metadata: os.stat_result) -> bool:
    return stat.S_ISREG(metadata.st_mode) and not _reparse(metadata)


def _reparse(metadata: os.stat_result) -> bool:
    return bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def cleanup_media(
    db: sqlite3.Connection, root: Path, now: float, retention: int
) -> MediaCleanupResult:
    # The caller holds the same SQLite writer lock as every manifest writer.
    try:
        references = _references(db, now, retention)
    except (ValueError, TypeError, KeyError, OverflowError):
        return MediaCleanupResult(errors=1, reason="invalid_manifest")
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return MediaCleanupResult()
    except OSError:
        return MediaCleanupResult(errors=1, reason="media_directory_unavailable")
    if not stat.S_ISDIR(metadata.st_mode) or _reparse(metadata):
        return MediaCleanupResult(errors=1, reason="unsafe_media_directory")
    deleted = size = retained = errors = 0
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    metadata = entry.stat(follow_symlinks=False)
                    if (
                        not _regular(metadata)
                        or not (_is_digest(entry.name) or _is_temporary(entry.name))
                        or entry.name in references
                        or metadata.st_mtime + ORPHAN_GRACE_SECONDS > now
                    ):
                        retained += 1
                        continue
                    Path(entry.path).unlink()
                    deleted += 1
                    size += metadata.st_size
                except OSError:
                    retained += 1
                    errors += 1
    except OSError:
        errors += 1
    return MediaCleanupResult(
        deleted, size, retained, errors, "file_cleanup_error" if errors else None
    )
