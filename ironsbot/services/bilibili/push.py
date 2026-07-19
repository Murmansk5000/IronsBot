from dataclasses import dataclass, replace
from typing import Any, Literal

from ironsbot.services.bilibili.parser import (
    dynamic_brief,
    dynamic_suppression_reason,
    item_author_mid,
    item_author_name,
)

DynamicPushStatus = Literal[
    "skip_existing",
    "suppressed",
    "no_targets",
    "push",
]


@dataclass(frozen=True, slots=True)
class DynamicHistorySnapshot:
    item: dict[str, Any]
    pub_ts: int
    author_mid: int
    author_name: str
    brief: str
    pushed: bool = False
    suppressed: bool = False
    suppression_reason: str = ""


@dataclass(frozen=True, slots=True)
class DynamicPushDecision:
    status: DynamicPushStatus

    @property
    def should_push(self) -> bool:
        return self.status == "push"


def build_dynamic_history_snapshot(
    item: dict[str, Any],
    *,
    pub_ts: int,
    author_mid: int,
    suppression_reason: str = "",
    pushed: bool = False,
) -> DynamicHistorySnapshot:
    return DynamicHistorySnapshot(
        item=item,
        pub_ts=pub_ts,
        author_mid=author_mid,
        author_name=item_author_name(item),
        brief=dynamic_brief(item),
        pushed=pushed,
        suppressed=bool(suppression_reason),
        suppression_reason=suppression_reason,
    )


def build_dynamic_history_snapshot_for_item(
    item: dict[str, Any],
    *,
    pub_ts: int,
    suppress_patterns: list[str],
    pushed: bool = False,
) -> DynamicHistorySnapshot | None:
    author_mid = item_author_mid(item)
    if not author_mid:
        return None

    suppression_reason = dynamic_suppression_reason(
        item,
        suppress_patterns,
    )
    return build_dynamic_history_snapshot(
        item,
        pub_ts=pub_ts,
        author_mid=author_mid,
        suppression_reason=suppression_reason,
        pushed=pushed,
    )


def mark_history_snapshot_pushed(
    snapshot: DynamicHistorySnapshot,
) -> DynamicHistorySnapshot:
    return replace(snapshot, pushed=True)


def decide_dynamic_push_before_targets(
    *,
    pub_ts: int,
    last_saved_time: int,
    suppression_reason: str,
) -> DynamicPushDecision | None:
    if pub_ts <= last_saved_time:
        return DynamicPushDecision(status="skip_existing")

    if suppression_reason:
        return DynamicPushDecision(status="suppressed")

    return None


def decide_dynamic_push_after_targets(
    *,
    has_targets: bool,
) -> DynamicPushDecision:
    if not has_targets:
        return DynamicPushDecision(status="no_targets")

    return DynamicPushDecision(status="push")
