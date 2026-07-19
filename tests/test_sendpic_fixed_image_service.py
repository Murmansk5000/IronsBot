import asyncio
from pathlib import Path

from ironsbot.core.messaging import FIXED_IMAGE_COMMANDS, SendpicBehaviorConfig
from ironsbot.integrations.sendpic import LocalBackend
from ironsbot.services.messaging.sendpic import SendpicService


def _service(root: Path) -> SendpicService:
    backend = LocalBackend(root)
    return SendpicService(
        SendpicBehaviorConfig(),
        lambda _kind: backend,
    )


def test_sendpic_service_returns_none_for_missing_fixed_image(
    tmp_path: Path,
) -> None:
    assert asyncio.run(_service(tmp_path).fixed_image("missing.png")) is None


def test_sendpic_service_reads_fixed_image(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"abc")

    assert asyncio.run(_service(tmp_path).fixed_image("sample.png")) == b"abc"


def test_anniversary_random_table_commands_use_same_fixed_image() -> None:
    assert FIXED_IMAGE_COMMANDS["周年庆伪随机表"] == "周年庆伪随机表.png"
    assert FIXED_IMAGE_COMMANDS["伪随机表"] == "周年庆伪随机表.png"


def test_skill_stone_is_fixed_image_command() -> None:
    assert FIXED_IMAGE_COMMANDS["技能石"] == "技能石.png"
