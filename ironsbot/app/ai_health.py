# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ironsbot.integrations.http.ai import AiApiSettings, check_ai_api

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiConfig


STARTUP_CHECK_TIMEOUT_SECONDS = 10.0


class StartupNoticeSink(Protocol):
    def add(
        self,
        subscription_key: str,
        action_name: str,
        message: str | None,
    ) -> None: ...


async def check_configured_ai_api(
    config: AiConfig,
    startup_notice: StartupNoticeSink,
) -> None:
    """Record the first healthy configured AI model for the startup notice."""

    if not config.api_key.strip():
        return

    failures: list[str] = []
    for model in config.models:
        result = await check_ai_api(
            AiApiSettings(
                api_key=config.api_key,
                base_url=config.base_url,
                model=model,
                timeout=min(config.timeout, STARTUP_CHECK_TIMEOUT_SECONDS),
                thinking=config.thinking,
            )
        )
        if result.ok:
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

    startup_notice.add(
        "startup_ai_api_check",
        "AI API startup check",
        "AI API 检查失败。\n"
        f"已尝试模型：{', '.join(config.models)}\n"
        f"详情：{'；'.join(failures)}",
    )
