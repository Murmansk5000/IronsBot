# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic, integrity-checked byte cache for disposable files."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_SHA256_HEX_LENGTH = 64
_FILENAME_DIGEST_LENGTH = 16
_ENTRY_KEY_LENGTH = 32
_SHA256_CHARACTERS = frozenset("0123456789abcdef")


class VerifiedFileCache:
    """Store byte values behind atomically replaced, checksum-backed entries."""

    def __init__(self, directory: Path, max_size_bytes: int) -> None:
        self._directory = directory
        self._max_size_bytes = max_size_bytes
        self._lock = RLock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            entry_key = _entry_key(key)
            index_path = self._index_path(entry_key)
            try:
                metadata = json.loads(index_path.read_text(encoding="utf-8"))
                digest = str(metadata["sha256"])
                if not _is_sha256(digest):
                    index_path.unlink(missing_ok=True)
                    return None
                asset_path = self._asset_path(entry_key, digest)
                asset = asset_path.read_bytes()
            except (FileNotFoundError, OSError, TypeError, ValueError, KeyError):
                return None
            if hashlib.sha256(asset).hexdigest() != digest:
                self._remove_entry(index_path, asset_path)
                return None
            try:
                os.utime(asset_path, None)
            except OSError:
                return None
            return asset

    def put(self, key: str, asset: bytes) -> None:
        with self._lock:
            entry_key = _entry_key(key)
            digest = hashlib.sha256(asset).hexdigest()
            asset_path = self._asset_path(entry_key, digest)
            index_path = self._index_path(entry_key)
            self._directory.mkdir(parents=True, exist_ok=True)
            self._atomic_write_bytes(asset_path, asset)
            self._atomic_write_text(
                index_path,
                json.dumps({"sha256": digest}, separators=(",", ":")),
            )
            self._cleanup()

    def cleanup(self) -> None:
        with self._lock:
            self._cleanup()

    def _cleanup(self) -> None:
        if not self._directory.exists():
            return
        indexed_assets = self._indexed_assets()
        assets = [
            path
            for path in self._directory.glob("*.bin")
            if path.name in indexed_assets
        ]
        for orphan in self._directory.glob("*.bin"):
            if orphan.name not in indexed_assets:
                orphan.unlink(missing_ok=True)
        assets.sort(
            key=lambda path: path.stat().st_atime,
        )
        total_size = sum(path.stat().st_size for path in assets)
        for asset_path in assets:
            if total_size <= self._max_size_bytes:
                break
            total_size -= asset_path.stat().st_size
            asset_path.unlink(missing_ok=True)
            if (index_path := indexed_assets.get(asset_path.name)) is not None:
                index_path.unlink(missing_ok=True)

    def _indexed_assets(self) -> dict[str, Path]:
        indexed: dict[str, Path] = {}
        for index_path in self._directory.glob("*.json"):
            try:
                metadata = json.loads(index_path.read_text(encoding="utf-8"))
                digest = str(metadata["sha256"])
            except (OSError, TypeError, ValueError, KeyError):
                index_path.unlink(missing_ok=True)
                continue
            if not _is_sha256(digest):
                index_path.unlink(missing_ok=True)
                continue
            asset_path = self._asset_path(index_path.stem, digest)
            if asset_path.exists():
                indexed[asset_path.name] = index_path
            else:
                index_path.unlink(missing_ok=True)
        return indexed

    def _index_path(self, entry_key: str) -> Path:
        return self._directory / f"{entry_key}.json"

    def _asset_path(self, entry_key: str, digest: str) -> Path:
        return self._directory / f"{entry_key}-{digest[:_FILENAME_DIGEST_LENGTH]}.bin"

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    @staticmethod
    def _atomic_write_text(path: Path, value: str) -> None:
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _remove_entry(index_path: Path, asset_path: Path) -> None:
        index_path.unlink(missing_ok=True)
        asset_path.unlink(missing_ok=True)


def _entry_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:_ENTRY_KEY_LENGTH]


def _is_sha256(value: str) -> bool:
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in _SHA256_CHARACTERS for character in value
    )
