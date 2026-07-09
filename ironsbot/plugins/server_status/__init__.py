# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.shared.plugin_system import register_plugin

from . import handlers as handlers
from .docker_update import (
    DockerUpdateResult,
    WatchtowerUpdateOptions,
    create_watchtower_container,
    format_docker_image_created,
    split_docker_image,
)
from .docker_update import (
    format_docker_update_reply as _format_docker_update_reply,
)
from .docker_update import (
    is_docker_update_started as _is_docker_update_started,
)
from .docker_update import (
    resolve_docker_container_name as _resolve_docker_container_name,
)
from .metadata import __plugin_meta__
from .plugin import ServerStatusPlugin
from .restart import DockerSelfUpdateService, RestartService

register_plugin(ServerStatusPlugin())

_format_docker_image_created = format_docker_image_created
_split_docker_image = split_docker_image
_create_watchtower_container = create_watchtower_container

__all__ = [
    "DockerSelfUpdateService",
    "DockerUpdateResult",
    "RestartService",
    "WatchtowerUpdateOptions",
    "__plugin_meta__",
    "_create_watchtower_container",
    "_format_docker_image_created",
    "_format_docker_update_reply",
    "_is_docker_update_started",
    "_resolve_docker_container_name",
    "_split_docker_image",
]
