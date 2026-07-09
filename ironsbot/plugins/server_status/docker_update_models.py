# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DockerImageInfo:
    image_id: str
    created: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WatchtowerUpdateOptions:
    image: str
    docker_api_version: str


@dataclass(frozen=True, slots=True)
class DockerUpdateResult:
    ok: bool
    message: str = ""
    updater_container_id: str = ""
    up_to_date: bool = False
    current_image_id: str = ""
    current_image_created: str = ""
    current_image_commit: str = ""
    target_image_id: str = ""
    target_image_created: str = ""
    target_image_commit: str = ""
    missing_socket: bool = False
