from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from ironsbot.services.bilibili.parser import item_author_mid, item_author_name

DynamicItem = tuple[int, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class InitializedCheckpoint:
    author_mid: int
    pub_ts: int
    author_name: str


def latest_seen_by_uid(
    valid_dynamics: Sequence[DynamicItem],
) -> dict[int, DynamicItem]:
    latest_seen: dict[int, DynamicItem] = {}
    for pub_ts, item in valid_dynamics:
        author_mid = item_author_mid(item)
        if not author_mid:
            continue

        saved_pub_ts, _ = latest_seen.get(author_mid, (0, {}))
        if pub_ts > saved_pub_ts:
            latest_seen[author_mid] = (pub_ts, item)

    return latest_seen


def initialize_missing_checkpoints(
    checkpoints: MutableMapping[int, int],
    valid_dynamics: Sequence[DynamicItem],
) -> list[InitializedCheckpoint]:
    initialized: list[InitializedCheckpoint] = []
    for author_mid, (pub_ts, item) in latest_seen_by_uid(valid_dynamics).items():
        if checkpoints.get(author_mid, 0) > 0:
            continue

        checkpoints[author_mid] = pub_ts
        initialized.append(
            InitializedCheckpoint(
                author_mid=author_mid,
                pub_ts=pub_ts,
                author_name=item_author_name(item),
            )
        )

    return initialized


def mark_checkpoint(
    checkpoints: MutableMapping[int, int],
    author_mid: int,
    pub_ts: int,
) -> bool:
    old_value = checkpoints.get(author_mid, 0)
    checkpoints[author_mid] = max(old_value, pub_ts)
    return checkpoints[author_mid] != old_value
