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

    available: list[str] = []
    failures: list[str] = []
    for endpoint in config.endpoints:
        if not endpoint.api_key.strip():
            failures.append(f"{endpoint.name}：未配置 {endpoint.key_environment_name}")
            continue
        for model in endpoint.models:
            result = await check_ai_api(
                AiApiSettings(
                    api_key=endpoint.api_key,
                    base_url=endpoint.base_url,
                    model=model,
                    timeout=min(config.timeout, _STARTUP_CHECK_TIMEOUT_SECONDS),
                    thinking=config.thinking,
                )
            )
            if result.ok:
                logger.info(
                    "AI API startup check passed: endpoint={} model={} HTTP {} {} ms",
                    endpoint.name,
                    model,
                    result.status_code,
                    result.elapsed_ms,
                )
                available.append(
                    f"{endpoint.name}/{model}"
                    f"（HTTP {result.status_code}，{result.elapsed_ms} ms）"
                )
                break
            failures.append(f"{endpoint.name}/{model}：{result.error}")

    if available:
        startup_notice.add(
            "startup_ai_api_check",
            "AI API startup check",
            "AI API 检查完成。\n"
            f"可用：{'；'.join(available)}"
            + (f"\n不可用：{'；'.join(failures)}" if failures else ""),
        )
        return

    logger.error("AI API startup check failed: {}", "; ".join(failures))
    endpoint_names = ", ".join(endpoint.name for endpoint in config.endpoints)
    startup_notice.add(
        "startup_ai_api_check",
        "AI API startup check",
        "AI API 检查失败。\n"
        f"已配置端点：{endpoint_names or '无'}\n"
        f"详情：{'；'.join(failures)}",
    )
