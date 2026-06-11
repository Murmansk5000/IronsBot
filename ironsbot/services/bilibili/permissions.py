from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.shared.features import (
    get_superuser_ids,
    is_event_feature_allowed,
)


def get_bili_superuser_uids() -> list[int]:
    return sorted(get_superuser_ids())


def is_bili_superuser(user_id: int) -> bool:
    return user_id in get_bili_superuser_uids()


def is_dynamic_query_allowed(event: MessageEvent) -> bool:
    return is_event_feature_allowed(event, "bili_query")


def is_dynamic_update_allowed(event: MessageEvent) -> bool:
    return is_bili_superuser(event.user_id)
