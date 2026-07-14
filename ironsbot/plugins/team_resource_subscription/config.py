from __future__ import annotations

from ironsbot.config.loader import get_app_config
from ironsbot.config.models.seer import (
    TeamResourceConfig,
    TeamResourceSubscriptionConfig,
)


def _resolve_int_ref(value: str | int, aliases: dict[str, int]) -> int | None:
    if isinstance(value, int):
        return value

    raw = str(value).strip()
    if not raw:
        return None
    if raw in aliases:
        return aliases[raw]
    if raw.isdigit():
        return int(raw)
    return None


def get_team_resource_config() -> TeamResourceConfig:
    return get_app_config().seer.team_resource


def get_team_resource_subscriptions() -> list[TeamResourceSubscriptionConfig]:
    config = get_team_resource_config()
    if not config.enabled:
        return []
    return [
        subscription
        for subscription in config.subscriptions
        if subscription.group and subscription.team_ids
    ]


def resolve_group_id(value: str | int) -> int | None:
    return _resolve_int_ref(value, get_app_config().feature.group_aliases)


def resolve_user_id(value: str | int) -> int | None:
    return _resolve_int_ref(value, get_app_config().feature.user_aliases)


def subscriptions_for_group(group_id: int) -> list[TeamResourceSubscriptionConfig]:
    return [
        subscription
        for subscription in get_team_resource_subscriptions()
        if resolve_group_id(subscription.group) == group_id
    ]


def at_users_for_subscription(
    subscription: TeamResourceSubscriptionConfig,
) -> list[int]:
    return [
        user_id
        for user_id in (resolve_user_id(user_ref) for user_ref in subscription.at_users)
        if user_id is not None
    ]


__all__ = [
    "TeamResourceConfig",
    "TeamResourceSubscriptionConfig",
    "at_users_for_subscription",
    "get_team_resource_config",
    "get_team_resource_subscriptions",
    "resolve_group_id",
    "resolve_user_id",
    "subscriptions_for_group",
]
