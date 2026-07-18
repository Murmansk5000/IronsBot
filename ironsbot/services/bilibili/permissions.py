from nonebot.adapters.onebot.v11 import MessageEvent

from ironsbot.shared.features import FeatureService
from ironsbot.shared.features.visibility import event_has_feature


def is_dynamic_query_allowed(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return event_has_feature(features, event, "bili_query")


def is_dynamic_update_allowed(
    features: FeatureService,
    event: MessageEvent,
) -> bool:
    return features.is_superuser(event.user_id)
