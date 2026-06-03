from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.custom_plugins.superuser_policy import (
    get_superuser_ids,
    is_group_allowed_for_user,
)

from .state import TARGET_GROUP_IDS, TARGET_USER_IDS


def get_bili_superuser_uids() -> list[int]:
    return sorted(get_superuser_ids())


def is_bili_superuser(user_id: int) -> bool:
    return user_id in get_bili_superuser_uids()


def is_dynamic_query_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            TARGET_GROUP_IDS,
        )

    if isinstance(event, PrivateMessageEvent):
        return event.user_id in TARGET_USER_IDS or is_bili_superuser(event.user_id)

    return False


def is_dynamic_update_allowed(event: MessageEvent) -> bool:
    if not is_bili_superuser(event.user_id):
        return False

    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            TARGET_GROUP_IDS,
        )

    return isinstance(event, PrivateMessageEvent)
