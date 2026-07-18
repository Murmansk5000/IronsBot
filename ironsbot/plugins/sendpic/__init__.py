from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.sendpic_fixed_image import FIXED_IMAGE_COMMANDS

from .config import enabled_pic_configs, get_sendpic_config
from .fixed_images import install as install_fixed_images
from .matchers import install as install_configured_images


def _format_command_names(command: str, aliases: set[str]) -> str:
    names = [command, *sorted(aliases)]
    return " / ".join(names)


def _format_config_command_help() -> list[str]:
    lines: list[str] = []
    for config in enabled_pic_configs(get_sendpic_config()):
        if config.help_message:
            lines.append(config.help_message)
            continue

        names = _format_command_names(config.command, config.aliases)
        lines.append(f"{names} — 随机或指定编号发送图片")
    return lines


def _format_fixed_image_help() -> list[str]:
    filename_to_commands: dict[str, list[str]] = {}
    for command, filename in FIXED_IMAGE_COMMANDS.items():
        filename_to_commands.setdefault(filename, []).append(command)

    lines: list[str] = []
    for filename, commands in filename_to_commands.items():
        name = filename.rsplit(".", 1)[0]
        lines.append(f"{' / '.join(commands)} — 发送{name}")
    return lines


def build_usage() -> str:
    command_help = [
        *_format_fixed_image_help(),
        *_format_config_command_help(),
    ]
    return """图片发送

命令：
""" + "\n".join(command_help)


def install(registry: MatcherRegistry) -> None:
    install_fixed_images(registry)
    install_configured_images(registry)


__all__ = ["build_usage", "install"]
