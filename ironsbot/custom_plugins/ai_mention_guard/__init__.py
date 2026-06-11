from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.shared.config.config import get_shared_config
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)

from .service import GuardReplyLimiter, should_guard_non_ai_group_mention

plugin_config = get_shared_config()
ai_config = plugin_config.ai_config
_guard_reply_limiter = GuardReplyLimiter(
    window_seconds=ai_config.mention_guard_reply_window_seconds,
    max_per_window=ai_config.mention_guard_reply_max_per_window,
)
AI_MENTION_GUARD_PLUGIN_NAME = "ai_mention_guard"

__plugin_meta__ = PluginMetadata(
    name="AI @ 提示拦截",
    description="在未启用 AI 聊天的群里拦截 @机器人，避免普通查询被 @ 触发。",
    usage=(
        "@机器人不会触发普通查询；"
        "未启用 AI 的群会提示直接发送指令，或发送“帮助”查看用法。"
    ),
)


async def _is_non_ai_group_at_guarded_user(event: MessageEvent) -> bool:
    return await should_guard_non_ai_group_mention(event)


mention_guard_matcher = on_message(
    rule=Rule(_is_non_ai_group_at_guarded_user),
    priority=0,
    block=True,
)


class AiMentionGuardPlugin:
    name = AI_MENTION_GUARD_PLUGIN_NAME
    feature = "ai_chat"
    enabled = True

    async def handle(
        self,
        event: GroupMessageEvent,
        context: PluginContext,
    ) -> None:
        if not _guard_reply_limiter.can_send(event.group_id):
            return

        await finish_event_reply(
            context.matcher or mention_guard_matcher,
            event,
            ai_config.mention_guard_message,
            mention_sender=True,
        )


register_plugin(AiMentionGuardPlugin())


@mention_guard_matcher.handle()
async def handle_non_ai_group_at_bot(event: GroupMessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=AI_MENTION_GUARD_PLUGIN_NAME,
        event=event,
        matcher=mention_guard_matcher,
    )
