from __future__ import annotations

from ironsbot.config.loader import get_app_config
from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.services.team_resource_subscriptions import (
    TeamResourceSubscription,
    TeamResourceSubscriptionStore,
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


def get_team_resource_store() -> TeamResourceSubscriptionStore:
    return TeamResourceSubscriptionStore(get_team_resource_config().subscription_path)


def get_team_resource_subscriptions() -> list[TeamResourceSubscription]:
    config = get_team_resource_config()
    if not config.enabled:
        return []
    return get_team_resource_store().list_all()


def resolve_group_id(value: str | int) -> int | None:
    return _resolve_int_ref(value, get_app_config().feature.group_aliases)


def resolve_user_id(value: str | int) -> int | None:
    return _resolve_int_ref(value, get_app_config().feature.user_aliases)


def subscriptions_for_group(group_id: int) -> list[TeamResourceSubscription]:
    config = get_team_resource_config()
    if not config.enabled:
        return []
    return get_team_resource_store().list_group(group_id)


def at_users_for_subscription(
    subscription: TeamResourceSubscription,
) -> list[int]:
    return list(subscription.at_user_ids)


def default_at_user_ids() -> tuple[int, ...]:
    config = get_team_resource_config()
    user_ids = [
        user_id
        for user_id in (
            resolve_user_id(user_ref) for user_ref in config.default_at_users
        )
        if user_id is not None
    ]
    return tuple(dict.fromkeys(user_ids))


__all__ = [
    "TeamResourceConfig",
    "at_users_for_subscription",
    "default_at_user_ids",
    "get_team_resource_config",
    "get_team_resource_store",
    "get_team_resource_subscriptions",
    "resolve_group_id",
    "resolve_user_id",
    "subscriptions_for_group",
]
