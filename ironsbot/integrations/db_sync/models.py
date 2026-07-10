# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, NamedTuple

import httpx

if TYPE_CHECKING:
    from datetime import datetime

    from ironsbot.config.models.runtime import RemoteBuildConfig

GetFingerprintFn = Callable[[httpx.AsyncClient], Awaitable[str]]


class SyncEntry(NamedTuple):
    sync_url: str
    sync_interval_minutes: int
    get_fingerprint: GetFingerprintFn | None = None
    local_path: str | None = None
    remote_build: RemoteBuildConfig | None = None


class VersionInfo(NamedTuple):
    fingerprint: str | None = None
    timestamp: datetime | None = None


class SyncStatus(NamedTuple):
    ok: bool
    skipped: bool = False
    local_before: VersionInfo = VersionInfo()
    remote: VersionInfo = VersionInfo()
    message: str = ""
