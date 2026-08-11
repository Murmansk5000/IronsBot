from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.log import logger

from ironsbot.integrations.http.ai import AiApiSettings, check_ai_api

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiConfig
    from ironsbot.services.operations.startup import StartupNoticeService


_STARTUP_CHECK_TIMEOUT_SECONDS = 10.0


async def check_configured_ai_api(
    config: AiConfig,
    startup_notice: StartupNoticeService,
) -> None:
    """Verify a configured AI endpoint without ever exposing its API key."""

    if not config.api_key.strip():
        return

    result = await check_ai_api(
        AiApiSettings(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=min(config.timeout, _STARTUP_CHECK_TIMEOUT_SECONDS),
            thinking=config.thinking,
        )
    )
    if result.ok:
        logger.info(
            "AI API startup check passed: HTTP {}, {} ms",
            result.status_code,
            result.elapsed_ms,
        )
        return

    logger.error("AI API startup check failed: {}", result.error)
    startup_notice.add(
        "startup_ai_api_check",
        "AI API startup check",
        "AI API Key 检查失败。\n"
        f"模型：{config.model}\n"
        f"详情：{result.error}",
    )
