# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable


class MessageTarget(NamedTuple):
    target_type: Literal["private", "group"]
    target_id: int
    at_user_ids: tuple[int, ...] = ()


class TargetSendSummary(NamedTuple):
    succeeded: list[MessageTarget]
    failed: list[MessageTarget]


def private_targets(user_ids: Iterable[int]) -> list[MessageTarget]:
    return [
        MessageTarget("private", user_id)
        for user_id in dict.fromkeys(user_ids)
    ]


def group_targets(
    group_ids: Iterable[int],
    *,
    at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    at_users = tuple(dict.fromkeys(at_user_ids))
    return [
        MessageTarget("group", group_id, at_users)
        for group_id in dict.fromkeys(group_ids)
    ]


def broadcast_targets(
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
) -> list[MessageTarget]:
    return [
        *group_targets(group_ids, at_user_ids=group_at_user_ids),
        *private_targets(private_user_ids),
    ]
