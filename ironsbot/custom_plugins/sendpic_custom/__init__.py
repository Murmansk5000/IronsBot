from nonebot.plugin import PluginMetadata

from .config import Config, filter_enabled_configs
from . import fixed_images as fixed_images
from .matchers import matcher_group as matcher_group

def _format_command_names(command: str, aliases: set[str]) -> str:
    names = [command, *sorted(aliases)]
    return " / ".join(names)


def _format_config_command_help() -> list[str]:
    lines: list[str] = []
    for config in filter_enabled_configs():
        if config.help_message:
            lines.append(config.help_message)
            continue

        names = _format_command_names(config.command, config.aliases)
        lines.append(f"{names} — 随机或指定编号发送图片")
    return lines


def _format_fixed_image_help() -> list[str]:
    filename_to_commands: dict[str, list[str]] = {}
    for command, filename in fixed_images.IMAGE_COMMANDS.items():
        filename_to_commands.setdefault(filename, []).append(command)

    lines: list[str] = []
    for filename, commands in filename_to_commands.items():
        name = filename.rsplit(".", 1)[0]
        lines.append(f"{' / '.join(commands)} — 发送{name}")
    return lines


command_help = [
    *_format_fixed_image_help(),
    *_format_config_command_help(),
]

usage = """图片发送

命令：
""" + "\n".join(command_help)

__plugin_meta__ = PluginMetadata(
    name="图片发送",
    description="发送固定图片或本地自定义图片",
    usage=usage,
    config=Config,
)
