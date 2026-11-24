# SPDX-License-Identifier: MIT
"""Narrow, credential-free contract for an optional Somua image provider."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from ironsbot.core.tasks import TaskSpawner

_UINT32_MAX = 0xFFFFFFFF
_IMAGE_SIZE = 768


@dataclass(frozen=True, slots=True)
class SomuaAvatarParts:
    body: int
    face: int
    hands: int
    ears: int
    tail: int
    head: int
    topwear: int
    back: int
    surround: int

    def __post_init__(self) -> None:
        if any(
            type(value := getattr(self, item.name)) is not int
            or not 0 <= value <= _UINT32_MAX
            for item in fields(self)
        ):
            message = "Somua parts must be unsigned 32-bit integers"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class SomuaAvatarRequest:
    parts: SomuaAvatarParts
    pose: str = "normal"
    time_seconds: float = 0
    width: int = _IMAGE_SIZE
    height: int = _IMAGE_SIZE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parts, SomuaAvatarParts)
            or self.pose != "normal"
            or isinstance(self.time_seconds, bool)
            or self.time_seconds != 0
            or type(self.width) is not int
            or type(self.height) is not int
            or self.width != _IMAGE_SIZE
            or self.height != _IMAGE_SIZE
        ):
            message = "Unsupported Somua avatar output specification"
            raise ValueError(message)


class SomuaAvatarUnavailable(RuntimeError):  # noqa: N818 - public capability outcome
    def __init__(self, reason_code: str, safe_message: str) -> None:
        self.reason_code = reason_code
        self.safe_message = safe_message
        super().__init__(safe_message)


class PreparedSomuaAvatar(Protocol):
    @property
    def resource_version(self) -> str: ...

    @property
    def renderer_fingerprint(self) -> str: ...

    @property
    def degraded(self) -> bool: ...

    @property
    def notice(self) -> str: ...

    async def render(self) -> bytes: ...


class SomuaAvatarProvider(Protocol):
    def prepare(
        self, request: SomuaAvatarRequest
    ) -> AbstractAsyncContextManager[PreparedSomuaAvatar]: ...


@dataclass(frozen=True, slots=True)
class SomuaAvatarExtensionContext:
    data_directory: Path
    settings: Mapping[str, object]
    spawn: TaskSpawner
    register_provider: Callable[[SomuaAvatarProvider], None]
