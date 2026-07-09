# SPDX-License-Identifier: MIT
from ironsbot.config.loader import get_app_config
from ironsbot.config.models.runtime import (
    DEFAULT_BROADCAST_MESSAGE,
    DockerUpdateConfig,
    ServerStatusConfig,
)


def get_server_status_config() -> ServerStatusConfig:
    return get_app_config().runtime.server_status


def get_docker_update_config() -> DockerUpdateConfig:
    return get_app_config().runtime.docker_update


__all__ = [
    "DEFAULT_BROADCAST_MESSAGE",
    "DockerUpdateConfig",
    "ServerStatusConfig",
    "get_docker_update_config",
    "get_server_status_config",
]
