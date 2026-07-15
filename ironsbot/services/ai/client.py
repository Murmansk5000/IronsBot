import httpx
from nonebot.log import logger

from ironsbot.config.loader import get_app_config
from ironsbot.services.ai.config import get_ai_key
from ironsbot.services.ai.constants import EMPTY_REPLY, REQUEST_FAILED_REPLY
from ironsbot.services.ai.history import HistoryMessage, build_messages
from ironsbot.services.ai.notifier import notify_superusers_once
from ironsbot.services.ai.responses import parse_ai_response
from ironsbot.services.ai.source_context import append_ai_notice_source_context

AI_CHAT_ERROR_SUBSCRIPTION_KEY = "ai_chat_error_notice"
AI_CHAT_ERROR_ACTION_NAME = "AI chat error notice"


def _truncate_reply(text: str) -> str:
    max_chars = get_app_config().ai.max_reply_chars
    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "\n\n（回复过长，已截断）"


async def call_ai_chat(
    prompt: str,
    history: list[HistoryMessage],
    memory: list[HistoryMessage] | None = None,
    *,
    source_context: str | None = None,
) -> str:
    config = get_app_config().ai
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
        "Authorization": f"Bearer {get_ai_key()}",
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

    result = parse_ai_response(response)
    if not result.ok and result.error_kind != "empty_reply":
        logger.warning(
            "AI chat API failed: "
            f"HTTP {result.status_code}, {result.error_detail}"
        )
        await notify_superusers_once(
            (
                f"http_{result.status_code}"
                if result.error_kind == "http"
                else str(result.error_kind)
            ),
            append_ai_notice_source_context(
                "AI聊天接口异常。\n"
                f"类型：{result.error_title}\n"
                f"HTTP：{result.status_code}\n"
                f"模型：{config.model}\n"
                f"接口：{config.base_url}\n"
                f"详情：{result.error_detail}\n"
                "请检查 AI_KEY、账户额度、模型名和网络连接。",
                source_context,
            ),
            subscription_key=AI_CHAT_ERROR_SUBSCRIPTION_KEY,
            action_name=AI_CHAT_ERROR_ACTION_NAME,
        )
        return REQUEST_FAILED_REPLY

    if result.error_kind == "empty_reply":
        await notify_superusers_once(
            "empty_reply",
            append_ai_notice_source_context(
                "AI聊天接口返回了空内容。\n"
                f"模型：{config.model}\n"
                "请检查模型配置或稍后重试。",
                source_context,
            ),
            subscription_key=AI_CHAT_ERROR_SUBSCRIPTION_KEY,
            action_name=AI_CHAT_ERROR_ACTION_NAME,
        )
        return EMPTY_REPLY

    return _truncate_reply(result.reply)
