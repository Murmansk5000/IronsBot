# SPDX-License-Identifier: MIT
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig


class ImageBackend(Protocol):
    async def count(self, path: str = "") -> int: ...

    async def get_file(self, file_path: str) -> bytes: ...


class InvalidImageArgumentError(Exception): ...


class ImageIndexOutOfRangeError(Exception):
    def __init__(self, max_index: int) -> None:
        self.max_index = max_index
        super().__init__(f"编号必须在1到{max_index}之间！")


@dataclass(frozen=True, slots=True)
class ImageSelection:
    index: int
    is_random: bool

    @property
    def random_text(self) -> str:
        return "随机" if self.is_random else "自选"


@dataclass(frozen=True, slots=True)
class SendpicResult:
    data: bytes
    index: int
    total: int
    random_text: str


class SendpicService:
    def __init__(
        self,
        config: SendpicBehaviorConfig,
        provider: Callable[[str], ImageBackend],
    ) -> None:
        self.commands = tuple(
            command
            for command in config.configs
            if command.id in config.enabled_ids
        )
        self._backends = {
            kind: provider(kind)
            for kind in {command.backend for command in self.commands}
        }
        self._fixed_backend = provider("fixed")

    async def fixed_image(self, filename: str) -> bytes | None:
        try:
            return await self._fixed_backend.get_file(filename)
        except FileNotFoundError:
            return None

    async def fetch(self, command: PicConfig, arg_text: str) -> SendpicResult:
        backend = self._backends[command.backend]
        total = await backend.count(command.image_dir)
        selection = select_image(arg_text, total)
        path = build_image_file_path(
            command.image_dir,
            command.image_filename_template,
            selection.index,
        )
        return SendpicResult(
            data=await backend.get_file(path),
            index=selection.index,
            total=total,
            random_text=selection.random_text,
        )


def select_image(
    arg_text: str,
    max_index: int,
    *,
    random_index_factory: Callable[[], int] | None = None,
) -> ImageSelection:
    if arg_text.isdigit():
        selection = ImageSelection(index=int(arg_text), is_random=False)
    elif not arg_text:
        index = (
            random.randint(1, max_index)  # nosec B311
            if random_index_factory is None
            else random_index_factory()
        )
        selection = ImageSelection(index=index, is_random=True)
    else:
        raise InvalidImageArgumentError
    if not 1 <= selection.index <= max_index:
        raise ImageIndexOutOfRangeError(max_index)
    return selection


def build_image_file_path(
    image_dir: str,
    image_filename_template: str,
    index: int,
) -> str:
    return f"{image_dir}/{image_filename_template.format(index=index)}"
