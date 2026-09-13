# SPDX-License-Identifier: MIT
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.affix_commands import AffixCommand
from ironsbot.core.command_catalog import CommandContract, parsed_command_input_matcher
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.outbound import (
    BinaryImagePart,
    OutboundMessage,
    format_outbound_message,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig


class ImageBackend(Protocol):
    async def count(self, path: str = "") -> int: ...

    async def get_file(self, file_path: str) -> bytes: ...


class ImageIndexOutOfRangeError(Exception):
    def __init__(self, max_index: int) -> None:
        self.max_index = max_index
        super().__init__(f"编号必须在1到{max_index}之间！")


class ImageNotFoundError(Exception): ...


@dataclass(frozen=True, slots=True)
class IndexedImageRequest:
    command_id: str
    index: int | None


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

    def to_outbound(self, template: str, *, command: str) -> OutboundMessage:
        return format_outbound_message(
            template,
            command=command,
            random_text=self.random_text,
            index=self.index,
            total=self.total,
            image=BinaryImagePart(self.data, "image/png"),
        )


class SendpicService:
    def __init__(
        self,
        config: SendpicBehaviorConfig,
        provider: Callable[[str], ImageBackend],
        *,
        command_starts: tuple[str, ...],
    ) -> None:
        self.command_starts = command_starts
        self.commands = tuple(
            command
            for command in config.configs
            if command.enabled and (command.mode == "single" or command_starts)
        )
        self._indexed_commands: dict[str, str] = {}
        for command in self.commands:
            if command.mode == "indexed":
                for start in command_starts:
                    for name in (command.command, *sorted(command.aliases)):
                        self._indexed_commands.setdefault(start + name, command.id)
        self._indexed_grammar = AffixCommand(
            tuple(sorted(self._indexed_commands, key=len, reverse=True)),
            (),
            ignorecase=False,
        )
        self._backends = {
            kind: provider(kind)
            for kind in {command.backend for command in self.commands}
        }

    def parse_indexed(self, text: str) -> IndexedImageRequest | None:
        parsed = self._indexed_grammar(text.lstrip())
        if parsed is None:
            return None
        argument = parsed.argument.lstrip()
        if argument and not argument.isdecimal():
            return None
        try:
            index = int(argument) if argument else None
        except ValueError:
            return None
        return IndexedImageRequest(self._indexed_commands[parsed.prefix], index)

    @property
    def exact_command_texts(self) -> frozenset[str]:
        return frozenset(
            normalize_command_text(start + text)
            for command in self.commands
            for start in (self.command_starts if command.mode == "indexed" else ("",))
            for text in (command.command, *command.aliases)
        )

    async def fetch_single(self, command: PicConfig) -> bytes:
        if command.mode != "single" or not command.image_file:
            raise ValueError(f"{command.id} 不是单图命令")  # noqa: TRY003
        try:
            return await self._backends[command.backend].get_file(command.image_file)
        except FileNotFoundError as exc:
            raise ImageNotFoundError from exc

    async def fetch_indexed(
        self,
        command: PicConfig,
        index: int | None,
    ) -> SendpicResult:
        if (
            command.mode != "indexed"
            or not command.image_dir
            or not command.image_filename_template
        ):
            raise ValueError(f"{command.id} 不是编号图库命令")  # noqa: TRY003
        backend = self._backends[command.backend]
        total = await backend.count(command.image_dir)
        selection = select_image(index, total)
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


def sendpic_command_contracts(
    service: SendpicService,
) -> tuple[CommandContract, ...]:
    """Describe exactly the configured image commands in the shared catalog."""

    contracts = []
    for config in service.commands:
        names = (config.command, *sorted(config.aliases))
        matches = None
        if config.mode == "indexed":
            prefix = "" if "" in service.command_starts else service.command_starts[0]
            examples = tuple(prefix + name for name in names)
            matches = parsed_command_input_matcher(
                service.parse_indexed,
                accepts=lambda parsed, command_id=config.id: (
                    parsed.command_id == command_id
                ),
            )
        else:
            examples = names
        contracts.append(
            CommandContract(
                id=f"sendpic.{config.id}",
                plugin_id="sendpic",
                section="图片",
                examples=examples,
                description=(
                    "发送配置的图片；可在命令后附加编号"
                    if config.mode == "indexed"
                    else "发送配置的图片"
                ),
                features_any=("image",),
                show_in_poke=True,
                routing_matcher=matches,
            )
        )
    return tuple(contracts)


def select_image(
    index: int | None,
    max_index: int,
    *,
    random_index_factory: Callable[[], int] | None = None,
) -> ImageSelection:
    is_random = index is None
    if index is None:
        index = (
            random.randint(1, max_index)  # nosec B311
            if random_index_factory is None
            else random_index_factory()
        )
    selection = ImageSelection(index=index, is_random=is_random)
    if not 1 <= selection.index <= max_index:
        raise ImageIndexOutOfRangeError(max_index)
    return selection


def build_image_file_path(
    image_dir: str,
    image_filename_template: str,
    index: int,
) -> str:
    return f"{image_dir}/{image_filename_template.format(index=index)}"
