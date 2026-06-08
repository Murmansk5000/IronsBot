from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.custom_plugins.feature_policy import (
    get_superuser_ids,
    is_event_feature_allowed,
)

from .state import TARGET_GROUP_IDS


def get_bili_superuser_uids() -> list[int]:
    return sorted(get_superuser_ids())


def is_bili_superuser(user_id: int) -> bool:
    return user_id in get_bili_superuser_uids()


def is_dynamic_query_allowed(event: MessageEvent) -> bool:
    return is_event_feature_allowed(event, "bili_query")


def is_dynamic_update_allowed(event: MessageEvent) -> bool:
    if not is_bili_superuser(event.user_id):
        return False

    if isinstance(event, GroupMessageEvent):
        return event.group_id in TARGET_GROUP_IDS

    return isinstance(event, PrivateMessageEvent)
