# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.integrations.db_sync.github_actions import WorkflowRunResult
    from ironsbot.integrations.db_sync.models import SyncEntry, SyncStatus

sync_locks: dict[str, asyncio.Lock] = {}
sync_all_lock = asyncio.Lock()
registered_syncs: dict[str, "SyncEntry"] = {}
registered_local_databases: dict[str, str] = {}
prepared_databases: set[str] = set()
fingerprints: dict[str, str] = {}
last_sync_statuses: dict[str, "SyncStatus"] = {}
remote_build_results: dict[str, "WorkflowRunResult"] = {}


def get_lock(name: str) -> asyncio.Lock:
    if name not in sync_locks:
        sync_locks[name] = asyncio.Lock()
    return sync_locks[name]
