from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from .mentions import mentions_bot
from .permissions import is_allowed as is_ai_allowed
from .resources import AiResources


async def should_guard_non_ai_group_mention(
    resources: AiResources,
    event: MessageEvent,
) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not mentions_bot(event):
        return False

    return not is_ai_allowed(resources.features, event)
