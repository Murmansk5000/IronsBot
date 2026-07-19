from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from ironsbot.services.bilibili.push import (
    build_dynamic_history_snapshot_for_item,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.bilibili.push import DynamicHistorySnapshot


class DynamicHistoryRecord(NamedTuple):
    dynamic_id: str
    uid: int
    author_name: str
    pub_ts: int
    brief: str
    item: dict[str, Any]
    pushed: bool
    suppressed: bool
    suppression_reason: str


class BiliDynamicHistoryStore(Protocol):
    def get_checkpoints(self) -> dict[int, int]: ...

    def save_checkpoints(self, checkpoints: dict[int, int]) -> None: ...

    def save_snapshot(self, snapshot: DynamicHistorySnapshot) -> None: ...

    def list(
        self,
        *,
        limit: int = 10,
        uid: int | None = None,
        uids: Iterable[int] | None = None,
    ) -> list[DynamicHistoryRecord]: ...

    def get(self, dynamic_id: str) -> DynamicHistoryRecord | None: ...


def save_target_dynamics(
    store: BiliDynamicHistoryStore,
    target_dynamics: Iterable[tuple[int, dict[str, Any]]],
    *,
    suppress_patterns: list[str],
) -> int:
    saved = 0
    for pub_ts, item in target_dynamics:
        snapshot = build_dynamic_history_snapshot_for_item(
            item,
            pub_ts=pub_ts,
            suppress_patterns=suppress_patterns,
        )
        if snapshot is not None:
            store.save_snapshot(snapshot)
            saved += 1
    return saved
