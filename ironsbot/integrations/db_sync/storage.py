# SPDX-License-Identifier: MIT
import hashlib
import logging
import os
import tempfile
from contextlib import suppress
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _write_bytes_atomic(file_path: str, content: bytes) -> None:
    target_path = Path(file_path)
    parent = target_path.parent
    if parent != Path():
        parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = parent if parent != Path() else Path.cwd()
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(tmp_dir),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        tmp_path.replace(target_path)
    finally:
        with suppress(FileNotFoundError):
            tmp_path.unlink()


def _normalize_fingerprint(raw: str | None) -> str | None:
    if raw is None:
        return None

    text = raw.strip()
    if not text:
        return None

    return text.split()[0].strip().lower() or None


def _fingerprint_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fingerprint_file(file_path: str | Path) -> str | None:
    path = Path(file_path)
    if not path.exists():
        return None

    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        logger.exception(f"读取本地数据库指纹失败: {path}")
        return None

    return digest.hexdigest()


def _file_timestamp(file_path: str | Path) -> datetime | None:
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        logger.exception(f"读取本地数据库时间失败: {path}")
        return None


def _parse_http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).astimezone()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


async def _fetch_remote_timestamp(
    client: httpx.AsyncClient,
    sync_url: str,
) -> datetime | None:
    try:
        response = await client.head(sync_url)
        response.raise_for_status()
    except (AttributeError, httpx.HTTPError):
        logger.debug(f"获取远端数据库时间失败: {sync_url}", exc_info=True)
        return None

    return _parse_http_datetime(response.headers.get("last-modified"))
