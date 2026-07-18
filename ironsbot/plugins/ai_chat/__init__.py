from functools import partial

import httpx
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.ai.chat import (
    build_ai_chat_context,
    can_show_admin_notice,
    get_ai_chat_key,
    is_ai_error_reply,
    record_successful_ai_reply,
)
from ironsbot.services.ai.client import call_ai_chat
from ironsbot.services.ai.mentions import mentions_bot
from ironsbot.services.ai.permissions import is_allowed, is_reserved_private_command
from ironsbot.services.ai.resources import AiResources
from ironsbot.services.ai.source_context import (
    append_ai_notice_source_context,
    build_notice_source,
)
from ironsbot.shared.matcher_priority import (
    get_matcher_priority,
    get_pre_command_matcher_priority,
)
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"
AI_CHAT_PRIORITY = get_matcher_priority("ai_chat", 99)
AI_GROUP_AT_CHAT_PRIORITY = get_pre_command_matcher_priority("ai_group_at")

async def _ai_chat_rule(
    event: MessageEvent,
    state: T_State,
    resources: AiResources,
) -> bool:
    if getattr(event, "reply", None) is not None:
        return False

    if not is_allowed(resources.features, event):
        return False

    if isinstance(event, GroupMessageEvent) and not mentions_bot(event):
        return False

    prompt = event.get_plaintext().strip()
    if is_reserved_private_command(event, prompt):
        return False

    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


async def _ai_chat_group_at_rule(
    event: GroupMessageEvent,
    state: T_State,
    resources: AiResources,
) -> bool:
    if getattr(event, "reply", None) is not None:
        return False

    if not is_allowed(resources.features, event):
        return False

    if not mentions_bot(event):
        return False

    state[AI_CHAT_PROMPT_KEY] = event.get_plaintext().strip()
    return True


async def _run_ai_chat(
    matcher: Matcher,
    bot: Bot,
    event: MessageEvent,
    state: T_State,
    resources: AiResources,
) -> None:
    prompt = state.get(AI_CHAT_PROMPT_KEY, "").strip()
    if not prompt:
        await finish_event_reply(
            matcher,
            event,
            "你想聊什么？可以 @我 后面直接写问题。",
            mention_sender=True,
        )

    key = get_ai_chat_key(event)
    source_context = await build_notice_source(event, prompt, resources, bot=bot)

    if not resources.api_key:
        await resources.notify_admin_once(
            "missing_api_key",
            append_ai_notice_source_context(
                "AI聊天还没有配置 API Key。\n"
                "请在 Unraid 容器变量或 .env.prod 中设置 AI_KEY。",
                source_context,
            ),
        )
        await _finish_admin_notice_or_silent(
            resources,
            matcher,
            event,
            "AI聊天还没有配置 API Key。请先设置 AI_KEY。",
        )

    config = resources.config
    if config.waiting_notice:
        await send_event_reply(
            matcher,
            event,
            "处理中...",
            mention_sender=True,
        )

    chat_context = build_ai_chat_context(resources, event, prompt, key=key)

    try:
        reply = await call_ai_chat(
            resources,
            prompt,
            chat_context.history,
            chat_context.memory,
            source_context=source_context,
        )
        if is_ai_error_reply(reply):
            await _finish_admin_notice_or_silent(resources, matcher, event, reply)

        if not is_ai_error_reply(reply):
            record_successful_ai_reply(resources, event, chat_context, reply)

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
        await resources.notify_admin_once(
            "timeout",
            append_ai_notice_source_context(
                "AI聊天接口响应超时。\n"
                f"接口：{config.base_url}\n"
                f"超时时间：{config.timeout} 秒\n"
                "请检查网络或适当调大 ai.timeout。",
                source_context,
            ),
        )
        await _finish_admin_notice_or_silent(
            resources,
            matcher,
            event,
            "AI接口响应超时，我已经通知超级管理员。",
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"AI chat failed: {e}")
        await resources.notify_admin_once(
            "unexpected",
            append_ai_notice_source_context(
                "AI聊天处理失败。\n"
                f"错误：{e}\n"
                "请查看容器日志确认具体原因。",
                source_context,
            ),
        )
        await _finish_admin_notice_or_silent(
            resources,
            matcher,
            event,
            "AI聊天出错了，我已经通知超级管理员。",
        )

async def _finish_admin_notice_or_silent(
    resources: AiResources,
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    if not can_show_admin_notice(resources, event):
        raise FinishedException

    await finish_event_reply(
        matcher,
        event,
        message,
        mention_sender=True,
    )


def install(registry: MatcherRegistry, resources: AiResources) -> None:
    direct_matcher = registry.on_message(
        policy=CommandPolicy.command("ai_chat"),
        rule=Rule(partial(_ai_chat_rule, resources=resources)),
        priority=AI_CHAT_PRIORITY,
        block=True,
    )
    direct_matcher.append_handler(partial(_run_ai_chat, resources=resources))

    group_at_matcher = registry.on_message(
        policy=CommandPolicy.command("ai_chat"),
        rule=Rule(partial(_ai_chat_group_at_rule, resources=resources)),
        priority=AI_GROUP_AT_CHAT_PRIORITY,
        block=True,
    )
    group_at_matcher.append_handler(partial(_run_ai_chat, resources=resources))
