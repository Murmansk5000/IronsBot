# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DockerImageInfo:
    image_id: str
    created: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    repo_digests: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WatchtowerUpdateOptions:
    image: str
    docker_api_version: str


@dataclass(frozen=True, slots=True)
class DockerRegistryCredentials:
    """Credentials used only while pulling an image from a private registry."""

    username: str
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class DockerUpdateRequest:
    container_name: str
    image: str
    socket_path: str
    watchtower: WatchtowerUpdateOptions
    timeout_seconds: float
    registry_credentials: DockerRegistryCredentials | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class DockerImageArchiveRequest:
    """Request a read-only directory archive from a Docker image."""

    image: str
    archive_path: str
    socket_path: str
    timeout_seconds: float
    registry_credentials: DockerRegistryCredentials | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class DockerImageArchive:
    image: DockerImageInfo
    content: bytes = field(repr=False)


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


@dataclass(frozen=True, slots=True)
class DockerImageCheckResult:
    """Result of comparing the running image with a registry manifest."""

    ok: bool
    message: str = ""
    up_to_date: bool = False
    current_image_id: str = ""
    current_image_created: str = ""
    current_image_commit: str = ""
    remote_digest: str = ""
    remote_image_id: str = ""
    remote_image_created: str = ""
    remote_image_commit: str = ""
    missing_socket: bool = False
