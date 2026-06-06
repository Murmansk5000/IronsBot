from collections.abc import Iterable

from nonebot import get_driver, get_plugin_config
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from pydantic import BaseModel, Field


class Config(BaseModel):
    admin_groups: list[int] = Field(default_factory=list)
    admin_bypass_groups: bool = False
    custom_feature_groups: list[int] = Field(default_factory=list)
    custom_feature_users: list[int] = Field(default_factory=list)


plugin_config = get_plugin_config(Config)


def _unique_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(values))


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_superuser_ids() -> set[int]:
    superusers = getattr(get_driver().config, "superusers", set())
    user_ids: set[int] = set()
    for user_id in superusers:
        if (int_user_id := _coerce_int(user_id)) is not None:
            user_ids.add(int_user_id)
    return user_ids


def get_admin_groups() -> list[int]:
    return _unique_ints(plugin_config.admin_groups)


def get_custom_feature_groups() -> list[int]:
    return _unique_ints(plugin_config.custom_feature_groups)


def get_custom_feature_users() -> list[int]:
    return _unique_ints(plugin_config.custom_feature_users)


def is_superuser(user_id: int) -> bool:
    return user_id in get_superuser_ids()


def with_superusers(user_ids: Iterable[int]) -> list[int]:
    return _unique_ints([*user_ids, *get_superuser_ids()])


def with_superuser_groups(group_ids: Iterable[int]) -> list[int]:
    return _unique_ints([*group_ids, *get_admin_groups()])


def is_private_user_allowed(user_id: int, user_ids: Iterable[int]) -> bool:
    return user_id in user_ids or is_superuser(user_id)


def is_group_allowed_for_user(
    user_id: int,
    group_id: int,
    group_ids: Iterable[int],
) -> bool:
    if group_id in with_superuser_groups(group_ids):
        return True

    return (
        plugin_config.admin_bypass_groups
        and is_superuser(user_id)
    )


def is_custom_feature_event_allowed(event: Event) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            get_custom_feature_groups(),
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(
            event.user_id,
            get_custom_feature_users(),
        )

    return False
