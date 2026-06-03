from __future__ import annotations

import time
from typing import Any

import httpx
from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    send_broadcast_message,
    send_event_reply,
)
from ironsbot.custom_plugins.superuser_policy import (
    get_superuser_ids,
    is_group_allowed_for_user,
    is_private_user_allowed,
)
from ironsbot.utils.rule import no_reply

from .config import Config, plugin_config

AI_CHAT_PROMPT_KEY = "_ai_chat_prompt"
SUPERUSER_NOTICE_COOLDOWN_SECONDS = 10 * 60
RESERVED_PRIVATE_COMMANDS = {
    "help",
    "帮助",
    "动态",
    "动态刷新",
    "动态更新",
    "刷新动态",
    "更新动态",
    "数据版本",
    "数据更新",
    "更新数据",
    "服务器状态",
    "签到",
    "活动",
    "链接",
}

__plugin_meta__ = PluginMetadata(
    name="AI聊天",
    description="接入 DeepSeek API 的自定义聊天插件",
    usage=(
        "群聊中 @机器人 并附带问题\n"
        "私聊中直接发送问题\n"
        "@机器人 清空聊天"
    ),
    config=Config,
)

_HISTORY: dict[str, list[dict[str, str]]] = {}
_LAST_SUPERUSER_NOTICE_AT: dict[str, float] = {}


def _get_first_bot():
    bots = get_driver().bots

    if not bots:
        return None

    return list(bots.values())[0]


async def _send_private_to_superusers(message: str) -> None:
    superuser_uids = get_superuser_ids()

    if not superuser_uids:
        logger.warning("AI聊天未配置管理员，无法发送异常提醒")
        return

    await send_broadcast_message(
        message,
        private_user_ids=sorted(superuser_uids),
        bot=_get_first_bot(),
        action_name="AI聊天异常提醒",
    )


async def _notify_superusers_once(key: str, message: str) -> None:
    now = time.time()
    last_notice_at = _LAST_SUPERUSER_NOTICE_AT.get(key, 0.0)

    if now - last_notice_at < SUPERUSER_NOTICE_COOLDOWN_SECONDS:
        return

    _LAST_SUPERUSER_NOTICE_AT[key] = now
    await _send_private_to_superusers(message)


def _is_reserved_private_command(event: MessageEvent, prompt: str) -> bool:
    if not isinstance(event, PrivateMessageEvent):
        return False

    normalized = "".join(prompt.split()).lower()
    return normalized in RESERVED_PRIVATE_COMMANDS


def _is_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_allowed_for_user(
            event.user_id,
            event.group_id,
            plugin_config.ai_chat_allowed_group_ids,
        )

    if isinstance(event, PrivateMessageEvent):
        return is_private_user_allowed(
            event.user_id,
            plugin_config.ai_chat_allowed_user_ids,
        )

    return False


async def _ai_chat_rule(event: MessageEvent, state: T_State) -> bool:
    if not _is_allowed(event):
        return False

    if isinstance(event, GroupMessageEvent):
        is_tome = getattr(event, "is_tome", None)
        if not callable(is_tome) or not is_tome():
            return False

    prompt = event.get_plaintext().strip()
    if _is_reserved_private_command(event, prompt):
        return False

    state[AI_CHAT_PROMPT_KEY] = prompt
    return True


ai_chat_matcher = on_message(
    rule=Rule(_ai_chat_rule) & no_reply(),
    priority=6,
    block=True,
)


def _history_key(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}:user:{event.user_id}"

    return f"private:{event.user_id}"


def _trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    if plugin_config.ai_chat_history_turns <= 0:
        return []

    max_messages = plugin_config.ai_chat_history_turns * 2
    return history[-max_messages:]


def _build_messages(
    history: list[dict[str, str]],
    prompt: str,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": plugin_config.ai_chat_system_prompt,
        }
    ]
    messages.extend(_trim_history(history))
    messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )
    return messages


def _is_reset_prompt(prompt: str) -> bool:
    normalized = "".join(prompt.split())

    return any(
        normalized == "".join(command.split())
        for command in plugin_config.ai_chat_reset_commands
    )


def _extract_reply(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content") or ""

    if isinstance(content, str):
        return content.strip()

    return ""


def _truncate_reply(text: str) -> str:
    max_chars = plugin_config.ai_chat_max_reply_chars

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "\n\n（回复过长，已截断）"


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]

    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or str(error)
        return str(message)[:300]

    return str(data)[:300]


def _api_error_title(status_code: int) -> str:
    if status_code in {401, 403}:
        return "密钥错误或没有接口权限"

    if status_code == 402:
        return "API额度不足或账户余额不足"

    if status_code == 429:
        return "请求过于频繁或触发限流"

    return "接口返回异常"


async def _call_deepseek(prompt: str, history: list[dict[str, str]]) -> str:
    payload = {
        "model": plugin_config.ai_chat_model,
        "messages": _build_messages(history, prompt),
        "temperature": plugin_config.ai_chat_temperature,
        "max_tokens": plugin_config.ai_chat_max_tokens,
        "stream": False,
        "thinking": {
            "type": (
                "enabled"
                if plugin_config.ai_chat_thinking_enabled
                else "disabled"
            )
        },
    }

    headers = {
        "Authorization": f"Bearer {plugin_config.ai_chat_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=plugin_config.ai_chat_timeout_seconds,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            f"{plugin_config.ai_chat_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

    if response.status_code >= 400:
        error_title = _api_error_title(response.status_code)
        error_detail = _extract_error_detail(response)

        logger.warning(
            "DeepSeek API 调用失败: "
            f"HTTP {response.status_code}, {error_detail}"
        )

        await _notify_superusers_once(
            f"http_{response.status_code}",
            "AI聊天接口异常。\n"
            f"类型：{error_title}\n"
            f"HTTP：{response.status_code}\n"
            f"模型：{plugin_config.ai_chat_model}\n"
            f"接口：{plugin_config.ai_chat_base_url}\n"
            f"详情：{error_detail}\n"
            "请检查 AI_CHAT_API_KEY、账户额度、模型名和网络连接。"
        )

        return "AI接口请求失败，我已经通知管理员。"

    reply = _extract_reply(response.json())

    if not reply:
        await _notify_superusers_once(
            "empty_reply",
            "AI聊天接口返回了空内容。\n"
            f"模型：{plugin_config.ai_chat_model}\n"
            "请检查模型配置或稍后重试。"
        )
        return "AI没有返回有效内容，请稍后再试。"

    return _truncate_reply(reply)


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

    key = _history_key(event)

    if _is_reset_prompt(prompt):
        _HISTORY.pop(key, None)
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "已清空这段聊天上下文。",
            mention_sender=True,
        )

    if not plugin_config.ai_chat_api_key:
        await _notify_superusers_once(
            "missing_api_key",
            "AI聊天还没有配置 API Key。\n"
            "请在 Unraid 容器变量或 .env.prod 中设置 AI_CHAT_API_KEY。"
        )

        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI聊天还没有配置 API Key。请先设置 AI_CHAT_API_KEY。",
            mention_sender=True,
        )

    if plugin_config.ai_chat_send_waiting_notice:
        await send_event_reply(
            ai_chat_matcher,
            event,
            "处理中...",
            mention_sender=True,
        )

    history = _HISTORY.get(key, [])

    try:
        reply = await _call_deepseek(prompt, history)

        if not reply.startswith("AI接口请求失败") and not reply.startswith(
            "AI没有返回有效内容"
        ):
            new_history = [
                *_trim_history(history),
                {
                    "role": "user",
                    "content": prompt,
                },
                {
                    "role": "assistant",
                    "content": reply,
                },
            ]
            _HISTORY[key] = _trim_history(new_history)

        await finish_event_reply(
            ai_chat_matcher,
            event,
            reply,
            mention_sender=True,
        )

    except FinishedException:
        raise

    except httpx.TimeoutException:
        logger.warning("DeepSeek API 调用超时")
        await _notify_superusers_once(
            "timeout",
            "AI聊天接口响应超时。\n"
            f"接口：{plugin_config.ai_chat_base_url}\n"
            f"超时时间：{plugin_config.ai_chat_timeout_seconds} 秒\n"
            "请检查网络或适当调大 AI_CHAT_TIMEOUT_SECONDS。"
        )
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI接口响应超时，我已经通知管理员。",
            mention_sender=True,
        )

    except Exception as e:
        logger.error(f"AI聊天处理失败: {e}")
        await _notify_superusers_once(
            "unexpected",
            "AI聊天处理失败。\n"
            f"错误：{e}\n"
            "请查看容器日志确认具体原因。"
        )
        await finish_event_reply(
            ai_chat_matcher,
            event,
            "AI聊天出错了，我已经通知管理员。",
            mention_sender=True,
        )
