import httpx
from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    send_event_reply,
)

from .client import EMPTY_REPLY, REQUEST_FAILED_REPLY, call_ai_chat
from .config import Config, plugin_config
from .constants import AI_CHAT_PROMPT_KEY
from .history import (
    append_turn,
    get_history,
    history_key,
    is_reset_prompt,
    reset_history,
)
from .memory import append_user_memory, get_user_memory, reset_user_memory
from .mentions import mentions_or_replies_to_bot
from .notifier import notify_superusers_once
from .permissions import is_allowed, is_reserved_private_command

__plugin_meta__ = PluginMetadata(
    name="AI聊天",
    description="接入 DeepSeek / OpenAI-compatible API 的自定义聊天插件",
    usage=(
        "群聊中 @机器人 并附带问题\n"
        "私聊中直接发送问题\n"
        "@机器人 清空聊天\n"
        "回复机器人消息也可以继续对话"
    ),
    config=Config,
)


async def _ai_chat_rule(event: MessageEvent, state: T_State) -> bool:
    if not is_allowed(event):
        return False

    if isinstance(event, GroupMessageEvent) and not mentions_or_replies_to_bot(event):
        return False

    prompt = event.get_plaintext().strip()
    if is_reserved_private_command(event, prompt):
        return False

    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


ai_chat_matcher = on_message(
    rule=Rule(_ai_chat_rule),
    priority=6,
    block=True,
)


@ai_chat_matcher.handle()
async def handle_ai_chat(event: MessageEvent, state: T_State) -> None:
    prompt = state.get(AI_CHAT_PROMPT_KEY, "").strip()
    if not prompt:
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "你想聊什么？可以 @我 后面直接写问题。",
            mention_sender=True,
        )

    key = history_key(event)
    if is_reset_prompt(prompt):
        reset_history(key)
        reset_user_memory(event.user_id)
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "已清空这段聊天上下文和你的长期记忆。",
            mention_sender=True,
        )

    if not plugin_config.ai_key:
        await notify_superusers_once(
            "missing_api_key",
            "AI聊天还没有配置 API Key。\n"
            "请在 Unraid 容器变量或 .env.prod 中设置 AI_KEY。",
        )
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI聊天还没有配置 API Key。请先设置 AI_KEY。",
            mention_sender=True,
        )

    if plugin_config.ai_waiting_notice:
        await send_event_reply(
            ai_chat_matcher,
            event,
            "处理中...",
            mention_sender=True,
        )

    history = get_history(key)
    memory = get_user_memory(
        event,
        current_session_key=key,
        has_short_history=bool(history),
    )

    try:
        reply = await call_ai_chat(prompt, history, memory)
        if reply not in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
            append_turn(key, prompt, reply)
            append_user_memory(
                event,
                session_key=key,
                prompt=prompt,
                reply=reply,
            )

        await finish_event_reply(
            ai_chat_matcher,
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
            "AI聊天接口响应超时。\n"
            f"接口：{plugin_config.ai_base_url}\n"
            f"超时时间：{plugin_config.ai_timeout} 秒\n"
            "请检查网络或适当调大 AI_TIMEOUT。",
        )
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI接口响应超时，我已经通知超级管理员。",
            mention_sender=True,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"AI chat failed: {e}")
        await notify_superusers_once(
            "unexpected",
            "AI聊天处理失败。\n"
            f"错误：{e}\n"
            "请查看容器日志确认具体原因。",
        )
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI聊天出错了，我已经通知超级管理员。",
            mention_sender=True,
        )
