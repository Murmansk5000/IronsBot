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

    failures: list[str] = []
    for model in config.models:
        result = await check_ai_api(
            AiApiSettings(
                api_key=config.api_key,
                base_url=config.base_url,
                model=model,
                timeout=min(config.timeout, _STARTUP_CHECK_TIMEOUT_SECONDS),
                thinking=config.thinking,
            )
        )
        if result.ok:
            logger.info(
                "AI API startup check passed: model={}, HTTP {}, {} ms",
                model,
                result.status_code,
                result.elapsed_ms,
            )
            startup_notice.add(
                "startup_ai_api_check",
                "AI API startup check",
                "AI API 检查通过。\n"
                f"模型：{model}\n"
                f"HTTP：{result.status_code}\n"
                f"耗时：{result.elapsed_ms} ms",
            )
            return
        failures.append(f"{model}：{result.error}")

    logger.error("AI API startup check failed: {}", "; ".join(failures))
    startup_notice.add(
        "startup_ai_api_check",
        "AI API startup check",
        "AI API 检查失败。\n"
        f"已尝试模型：{', '.join(config.models)}\n"
        f"详情：{'；'.join(failures)}",
    )
