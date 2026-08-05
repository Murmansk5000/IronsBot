import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig
from ironsbot.integrations.sendpic import LocalBackend
from ironsbot.services.messaging.sendpic import (
    ImageNotFoundError,
    SendpicService,
)


def _service(root: Path) -> SendpicService:
    backend = LocalBackend(root)
    return SendpicService(
        SendpicBehaviorConfig(),
        lambda _kind: backend,
    )


def test_sendpic_service_raises_for_missing_single_image(
    tmp_path: Path,
) -> None:
    command = PicConfig(
        id="missing",
        backend="builtin",
        command="missing",
        mode="single",
        image_file="missing.png",
    )

    with pytest.raises(ImageNotFoundError):
        asyncio.run(_service(tmp_path).fetch_single(command))


def test_sendpic_service_reads_single_image(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"abc")

    command = PicConfig(
        id="sample",
        backend="builtin",
        command="sample",
        mode="single",
        image_file="sample.png",
    )

    assert asyncio.run(_service(tmp_path).fetch_single(command)) == b"abc"


def test_packaged_single_image_aliases_use_one_config() -> None:
    service = _service(Path())
    commands = {command.id: command for command in service.commands}

    config = commands["anniversary-random-table"]
    assert config.command == "周年庆伪随机表"
    assert config.aliases == {"伪随机表"}
    assert config.image_file == "周年庆伪随机表.png"


def test_custom_config_can_disable_packaged_command() -> None:
    config = SendpicBehaviorConfig(
        configs=[
            {
                "id": "skill-stone",
                "enabled": False,
            }
        ]
    )

    enabled_ids = {command.id for command in config.configs if command.enabled}
    assert "skill-stone" not in enabled_ids


def test_custom_gallery_extends_packaged_commands_and_command_index() -> None:
    service = SendpicService(
        SendpicBehaviorConfig(
            configs=[
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
    )

    assert {command.id for command in service.commands} >= {
        "study-table",
        "example-gallery",
    }
    assert service.exact_command_texts >= {"学习力", "学习力表", "表情", "表情包"}


def test_legacy_enabled_ids_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SendpicBehaviorConfig(enabled_ids=["skill-stone"])  # type: ignore[call-arg]
