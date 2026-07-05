import httpx
from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.services.ai.chat import (
    build_ai_chat_context,
    can_show_admin_notice,
    get_ai_chat_key,
    is_ai_error_reply,
    record_successful_ai_reply,
    reset_ai_chat_context,
)
from ironsbot.services.ai.client import (
    AI_CHAT_ERROR_ACTION_NAME,
    AI_CHAT_ERROR_SUBSCRIPTION_KEY,
    call_ai_chat,
    get_ai_key,
)
from ironsbot.services.ai.history import is_reset_prompt
from ironsbot.services.ai.mentions import mentions_bot
from ironsbot.services.ai.notifier import notify_superusers_once
from ironsbot.services.ai.permissions import is_allowed, is_reserved_private_command
from ironsbot.services.ai.source_context import (
    append_ai_notice_source_context,
    build_ai_notice_source_context,
)
from ironsbot.shared.matcher_priority import (
    get_matcher_priority,
    get_pre_command_matcher_priority,
)
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)

from .config import Config, get_ai_config

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"
AI_CHAT_PRIORITY = get_matcher_priority("ai_chat", 99)
AI_GROUP_AT_CHAT_PRIORITY = get_pre_command_matcher_priority("ai_group_at")

__plugin_meta__ = PluginMetadata(
    name="AI聊天",
    description="接入 DeepSeek / OpenAI-compatible API 的自定义聊天插件",
    usage=(
        "群聊中 @机器人 并附带问题\n"
        "私聊中直接发送问题\n"
        "@机器人 清空聊天"
    ),
    config=Config,
)


async def _ai_chat_rule(event: MessageEvent, state: T_State) -> bool:
    if getattr(event, "reply", None) is not None:
        return False

    if not is_allowed(event):
        return False

    if isinstance(event, GroupMessageEvent) and not mentions_bot(event):
        return False

    prompt = event.get_plaintext().strip()
    if is_reserved_private_command(event, prompt):
        return False

    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


async def _ai_chat_group_at_rule(event: GroupMessageEvent, state: T_State) -> bool:
    if getattr(event, "reply", None) is not None:
        return False

    if not is_allowed(event):
        return False

    if not mentions_bot(event):
        return False

    state[AI_CHAT_PROMPT_KEY] = event.get_plaintext().strip()
    return True


class AiChatPlugin:
    name = "ai_chat"
    feature = "ai_chat"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher or ai_chat_matcher
        state = context.state if context.state is not None else {}
        prompt = state.get(AI_CHAT_PROMPT_KEY, "").strip()
        if not prompt:
            await finish_event_reply(
                matcher,
                event,
                "你想聊什么？可以 @我 后面直接写问题。",
                mention_sender=True,
            )

        key = get_ai_chat_key(event)
        source_context = build_ai_notice_source_context(event, prompt)
        if is_reset_prompt(prompt):
            reset_ai_chat_context(event, key)
            await finish_event_reply(
                matcher,
                event,
                "已清空这段聊天上下文和你的长期记忆。",
                mention_sender=True,
            )

        if not get_ai_key():
            await notify_superusers_once(
                "missing_api_key",
                append_ai_notice_source_context(
                    "AI聊天还没有配置 API Key。\n"
                    "请在 Unraid 容器变量或 .env.prod 中设置 AI_KEY。",
                    source_context,
                ),
                subscription_key=AI_CHAT_ERROR_SUBSCRIPTION_KEY,
                action_name=AI_CHAT_ERROR_ACTION_NAME,
            )
            await _finish_admin_notice_or_silent(
                event,
                "AI聊天还没有配置 API Key。请先设置 AI_KEY。",
            )

        config = get_ai_config()
        if config.waiting_notice:
            await send_event_reply(
                matcher,
                event,
                "处理中...",
                mention_sender=True,
            )

        chat_context = build_ai_chat_context(event, prompt, key=key)

        try:
            reply = await call_ai_chat(
                prompt,
                chat_context.history,
                chat_context.memory,
                source_context=source_context,
            )
            if is_ai_error_reply(reply):
                await _finish_admin_notice_or_silent(event, reply)

            if not is_ai_error_reply(reply):
                record_successful_ai_reply(event, chat_context, reply)

            await finish_event_reply(
                matcher,
                event,
                reply,
                mention_sender=True,
            )

        except FinishedException:
            raise
        except httpx.TimeoutException:
            logger.warning("AI chat API timed out")
            await notify_superusers_once(
                "timeout",
                append_ai_notice_source_context(
                    "AI聊天接口响应超时。\n"
                    f"接口：{config.base_url}\n"
                    f"超时时间：{config.timeout} 秒\n"
                    "请检查网络或适当调大 ai.timeout。",
                    source_context,
                ),
                subscription_key=AI_CHAT_ERROR_SUBSCRIPTION_KEY,
                action_name=AI_CHAT_ERROR_ACTION_NAME,
            )
            await _finish_admin_notice_or_silent(
                event,
                "AI接口响应超时，我已经通知超级管理员。",
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"AI chat failed: {e}")
            await notify_superusers_once(
                "unexpected",
                append_ai_notice_source_context(
                    "AI聊天处理失败。\n"
                    f"错误：{e}\n"
                    "请查看容器日志确认具体原因。",
                    source_context,
                ),
                subscription_key=AI_CHAT_ERROR_SUBSCRIPTION_KEY,
                action_name=AI_CHAT_ERROR_ACTION_NAME,
            )
            await _finish_admin_notice_or_silent(
                event,
                "AI聊天出错了，我已经通知超级管理员。",
            )


register_plugin(AiChatPlugin())


ai_chat_matcher = on_message(
    rule=Rule(_ai_chat_rule),
    priority=AI_CHAT_PRIORITY,
    block=True,
)

ai_chat_group_at_matcher = on_message(
    rule=Rule(_ai_chat_group_at_rule),
    priority=AI_GROUP_AT_CHAT_PRIORITY,
    block=True,
)


async def _finish_admin_notice_or_silent(
    event: MessageEvent,
    message: str,
) -> None:
    if not can_show_admin_notice(event):
        raise FinishedException

    await finish_event_reply(
        ai_chat_matcher,
        event,
        message,
        mention_sender=True,
    )


@ai_chat_matcher.handle()
async def handle_ai_chat(event: MessageEvent, state: T_State) -> None:
    await dispatch_plugin(
        plugin_name="ai_chat",
        event=event,
        matcher=ai_chat_matcher,
        state=state,
    )


@ai_chat_group_at_matcher.handle()
async def handle_group_at_ai_chat(event: GroupMessageEvent, state: T_State) -> None:
    await dispatch_plugin(
        plugin_name="ai_chat",
        event=event,
        matcher=ai_chat_group_at_matcher,
        state=state,
    )
