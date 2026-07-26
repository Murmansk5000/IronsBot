# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ironsbot.app.private_extensions import PrivateExtensionInstaller
from ironsbot.config.loader import (
    ConfigFileNotFoundError,
    TOMLDecodeError,
    load_settings,
)
from ironsbot.integrations.docker.client import DockerClient
from ironsbot.services.operations.docker_preflight import (
    DockerStartupPreflightAction,
    DockerStartupPreflightService,
    DockerStartupPreflightStore,
)
from ironsbot.services.operations.docker_update import DockerUpdateService

if TYPE_CHECKING:
    from ironsbot.config.models.operations import (
        DockerUpdateConfig,
        PrivateExtensionsConfig,
    )
    from ironsbot.config.models.settings import Settings

MISSING_CONFIG_EXIT_CODE = 2
STARTUP_PREFLIGHT_TIMEOUT_SECONDS = 20.0


async def _restart_not_available() -> None:
    msg = "docker startup preflight cannot restart the application process"
    raise RuntimeError(msg)


def startup_preflight_config(config: DockerUpdateConfig) -> DockerUpdateConfig:
    return config.model_copy(
        update={
            "timeout_seconds": min(
                float(config.timeout_seconds),
                STARTUP_PREFLIGHT_TIMEOUT_SECONDS,
            )
        }
    )


async def run_docker_startup_preflight(
    config: DockerUpdateConfig,
    *,
    store: DockerStartupPreflightStore | None = None,
) -> DockerStartupPreflightAction:
    update_service = DockerUpdateService(
        startup_preflight_config(config),
        DockerClient(),
        _restart_not_available,
    )
    return await DockerStartupPreflightService(
        config,
        update_service,
        store or DockerStartupPreflightStore(),
    ).run()


async def run_private_extensions_preflight(
    config: PrivateExtensionsConfig,
    docker_update: DockerUpdateConfig,
) -> None:
    await PrivateExtensionInstaller(
        config,
        docker_update,
        DockerClient(),
    ).install()


async def run_startup_preflight(settings: Settings) -> DockerStartupPreflightAction:
    action = await run_docker_startup_preflight(settings.operations.docker_update)
    if action is DockerStartupPreflightAction.CONTINUE:
        await run_private_extensions_preflight(
            settings.operations.private_extensions,
            settings.operations.docker_update,
        )
    return action


def main() -> int:
    try:
        settings = load_settings()
    except ConfigFileNotFoundError as error:
        sys.stderr.write(f"{error}\n")
        return MISSING_CONFIG_EXIT_CODE
    except (TOMLDecodeError, ValidationError, TypeError, ValueError) as error:
        sys.stderr.write(f"IronsBot 配置文件格式或字段错误：{error}\n")
        return MISSING_CONFIG_EXIT_CODE
    action = asyncio.run(run_startup_preflight(settings))
    return int(action)


if __name__ == "__main__":  # pragma: no cover - exercised by the Docker entrypoint
    raise SystemExit(main())
