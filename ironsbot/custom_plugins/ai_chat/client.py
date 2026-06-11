from typing import Any

import httpx
from nonebot.log import logger

from .config import plugin_config
from .constants import EMPTY_REPLY, REQUEST_FAILED_REPLY
from .history import HistoryMessage, build_messages
from .notifier import notify_superusers_once

HTTP_PAYMENT_REQUIRED = 402
HTTP_TOO_MANY_REQUESTS = 429
HTTP_BAD_REQUEST = 400


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
    max_chars = plugin_config.ai_config.max_reply_chars
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

    if status_code == HTTP_PAYMENT_REQUIRED:
        return "API额度不足或账户余额不足"

    if status_code == HTTP_TOO_MANY_REQUESTS:
        return "请求过于频繁或触发限流"

    return "接口返回异常"


async def call_ai_chat(
    prompt: str,
    history: list[HistoryMessage],
    memory: list[HistoryMessage] | None = None,
) -> str:
    config = plugin_config.ai_config
    payload = {
        "model": config.model,
        "messages": build_messages(history, prompt, memory),
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "stream": False,
        "thinking": {
            "type": (
                "enabled"
                if config.thinking
                else "disabled"
            )
        },
    }
    headers = {
        "Authorization": f"Bearer {plugin_config.ai_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=config.timeout,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            f"{config.base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

    if response.status_code >= HTTP_BAD_REQUEST:
        error_title = _api_error_title(response.status_code)
        error_detail = _extract_error_detail(response)
        logger.warning(
            "AI chat API failed: "
            f"HTTP {response.status_code}, {error_detail}"
        )
        await notify_superusers_once(
            f"http_{response.status_code}",
            "AI聊天接口异常。\n"
            f"类型：{error_title}\n"
            f"HTTP：{response.status_code}\n"
            f"模型：{config.model}\n"
            f"接口：{config.base_url}\n"
            f"详情：{error_detail}\n"
            "请检查 AI_KEY、账户额度、模型名和网络连接。",
        )
        return REQUEST_FAILED_REPLY

    reply = _extract_reply(response.json())
    if not reply:
        await notify_superusers_once(
            "empty_reply",
            "AI聊天接口返回了空内容。\n"
            f"模型：{config.model}\n"
            "请检查模型配置或稍后重试。",
        )
        return EMPTY_REPLY

    return _truncate_reply(reply)
