from collections.abc import Iterable

from nonebot import get_driver, get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    admin_groups: list[int] = Field(default_factory=list)
    admin_bypass_groups: bool = False


plugin_config = get_plugin_config(Config)


def _unique_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(values))


def get_superuser_ids() -> set[int]:
    superusers = getattr(get_driver().config, "superusers", set())
    user_ids: set[int] = set()
    for user_id in superusers:
        try:
            user_ids.add(int(user_id))
        except (TypeError, ValueError):
            continue
    return user_ids


def get_admin_groups() -> list[int]:
    return _unique_ints(plugin_config.admin_groups)


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
