from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.custom_plugins.ai_chat.permissions import is_allowed as is_ai_allowed
from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.custom_plugins.superuser_policy import get_superuser_ids
from ironsbot.utils.rule import no_reply

__plugin_meta__ = PluginMetadata(
    name="AI @ 提示拦截",
    description="在未启用 AI 聊天的群里拦截 @机器人，避免普通查询被 @ 触发。",
    usage="@机器人不会触发普通查询；未启用 AI 的群会提示直接发送指令。",
)


def _mentioned_user_ids(event: GroupMessageEvent) -> set[int]:
    user_ids: set[int] = set()
    for segment in event.message:
        if segment.type != "at":
            continue

        raw_qq = segment.data.get("qq")
        try:
            user_ids.add(int(raw_qq))
        except (TypeError, ValueError):
            continue

    return user_ids


def _mentions_bot_or_superuser(event: GroupMessageEvent) -> bool:
    is_tome = getattr(event, "is_tome", None)
    if callable(is_tome) and is_tome():
        return True

    return bool(_mentioned_user_ids(event) & get_superuser_ids())


async def _is_non_ai_group_at_guarded_user(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not _mentions_bot_or_superuser(event):
        return False

    return not is_ai_allowed(event)


mention_guard_matcher = on_message(
    rule=Rule(_is_non_ai_group_at_guarded_user) & no_reply(),
    priority=0,
    block=True,
)


@mention_guard_matcher.handle()
async def handle_non_ai_group_at_bot(event: GroupMessageEvent) -> None:
    await finish_event_reply(
        mention_guard_matcher,
        event,
        "这个群没有开启 AI 聊天，@之后不会触发功能。直接发送指令就可以查询。",
        mention_sender=True,
    )
