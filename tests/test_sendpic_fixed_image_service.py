import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig
from ironsbot.core.outbound import BinaryImagePart, TextPart
from ironsbot.integrations.sendpic import LocalBackend
from ironsbot.services.messaging.sendpic import (
    ImageNotFoundError,
    SendpicService,
    sendpic_command_contracts,
)


def _service(root: Path, *commands: PicConfig) -> SendpicService:
    backend = LocalBackend(root)
    return SendpicService(
        SendpicBehaviorConfig(configs=list(commands)),
        lambda _kind: backend,
        command_starts=("/", ""),
    )


def test_sendpic_service_raises_for_missing_single_image(
    tmp_path: Path,
) -> None:
    command = PicConfig(
        id="missing",
        backend="local",
        command="missing",
        mode="single",
        image_file="missing.png",
    )

    with pytest.raises(ImageNotFoundError):
        asyncio.run(_service(tmp_path, command).fetch_single(command))


def test_sendpic_service_reads_single_image(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"abc")

    command = PicConfig(
        id="sample",
        backend="local",
        command="sample",
        mode="single",
        image_file="sample.png",
    )

    result = asyncio.run(_service(tmp_path, command).fetch_single(command))

    assert result.data == b"abc"
    assert result.to_outbound().parts == (BinaryImagePart(b"abc", "image/png"),)


def test_indexed_image_result_owns_platform_neutral_template_output(
    tmp_path: Path,
) -> None:
    image_dir = tmp_path / "memes"
    image_dir.mkdir()
    (image_dir / "1.png").write_bytes(b"abc")
    command = PicConfig(
        id="gallery",
        backend="local",
        command="表情",
        mode="indexed",
        image_dir="memes",
        image_filename_template="{index}.png",
        message_template="{random_text}{index}/{total}\n{image}",
    )

    result = asyncio.run(_service(tmp_path, command).fetch_indexed(command, 1))

    assert result.to_outbound(
        command.message_template, command=command.command
    ).parts == (
        TextPart("自选1/1\n"),
        BinaryImagePart(b"abc", "image/png"),
    )


def test_image_commands_are_empty_by_default() -> None:
    assert SendpicBehaviorConfig().configs == []


def test_builtin_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PicConfig(
            id="legacy",
            backend="builtin",  # type: ignore[arg-type]
            command="legacy",
            mode="single",
            image_file="legacy.png",
        )


def test_custom_gallery_defines_complete_command_index() -> None:
    service = SendpicService(
        SendpicBehaviorConfig(
            configs=[  # type: ignore[reportArgumentType]
                {
                    "id": "example-gallery",
                    "backend": "local",
                    "command": "表情",
                    "aliases": ["表情包"],
                    "mode": "indexed",
                    "image_dir": "memes",
                    "image_filename_template": "{index}.png",
                }
            ]
        ),
        lambda _kind: LocalBackend(Path()),
        command_starts=("/", ""),
    )

    assert {command.id for command in service.commands} == {"example-gallery"}
    assert service.exact_command_texts == {"表情", "表情包", "/表情", "/表情包"}


def test_sendpic_command_contracts_follow_enabled_configurations() -> None:
    service = SendpicService(
        SendpicBehaviorConfig(
            configs=[  # type: ignore[reportArgumentType]
                {
                    "id": "example-gallery",
                    "backend": "local",
                    "command": "表情",
                    "aliases": ["表情包"],
                    "mode": "indexed",
                    "image_dir": "memes",
                    "image_filename_template": "{index}.png",
                }
            ]
        ),
        lambda _kind: LocalBackend(Path()),
        command_starts=("/", ""),
    )

    descriptors = {item.id: item for item in sendpic_command_contracts(service)}

    assert descriptors["sendpic.example-gallery"].examples == ("表情", "表情包")
    assert descriptors["sendpic.example-gallery"].description == (
        "发送配置的图片；可在命令后附加编号"
    )


def test_legacy_enabled_ids_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SendpicBehaviorConfig(enabled_ids=["skill-stone"])  # type: ignore[call-arg]


def test_duplicate_config_ids_are_rejected() -> None:
    config = {
        "id": "duplicate",
        "backend": "local",
        "command": "图片",
        "mode": "single",
        "image_file": "image.png",
    }
    with pytest.raises(ValidationError, match="图片命令 ID 重复"):
        SendpicBehaviorConfig(configs=[config, config])  # type: ignore[list-item]
