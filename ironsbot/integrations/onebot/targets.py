# SPDX-License-Identifier: MIT
"""Native OneBot proactive-delivery targets.

This is an adapter-only transition model.  Platform-neutral services use
``ActorRef`` and ``ConversationRef``; legacy OneBot batch delivery converts to
these numeric values only after the service boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable


class OneBotMessageTarget(NamedTuple):
    target_type: Literal["private", "group"]
    target_id: int
    at_user_ids: tuple[int, ...] = ()


class OneBotTargetSendSummary(NamedTuple):
    succeeded: list[OneBotMessageTarget]
    failed: list[OneBotMessageTarget]


def private_targets(user_ids: Iterable[int]) -> list[OneBotMessageTarget]:
    return [
        OneBotMessageTarget("private", user_id) for user_id in dict.fromkeys(user_ids)
    ]


def group_targets(
    group_ids: Iterable[int],
    *,
    at_user_ids: Iterable[int] = (),
) -> list[OneBotMessageTarget]:
    at_users = tuple(dict.fromkeys(at_user_ids))
    return [
        OneBotMessageTarget("group", group_id, at_users)
        for group_id in dict.fromkeys(group_ids)
    ]


def broadcast_targets(
    *,
    private_user_ids: Iterable[int] = (),
    group_ids: Iterable[int] = (),
    group_at_user_ids: Iterable[int] = (),
) -> list[OneBotMessageTarget]:
    return [
        *group_targets(group_ids, at_user_ids=group_at_user_ids),
        *private_targets(private_user_ids),
    ]
