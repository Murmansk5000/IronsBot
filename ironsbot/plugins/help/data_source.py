# SPDX-License-Identifier: MIT
"""插件帮助信息发现与格式化。

从 NoneBot 已加载的插件元信息中提取帮助文本，
支持按适配器、插件类型进行过滤。
"""

from typing import TYPE_CHECKING, cast

from nonebot import get_driver, get_loaded_plugins
from nonebot.rule import CommandRule, ShellCommandRule

from .config import plugin_config

if TYPE_CHECKING:
    from nonebot.adapters import Bot
    from nonebot.plugin import Plugin, PluginMetadata

global_config = get_driver().config

_plugins: dict[str, "Plugin"] | None = None
_commands: dict[tuple[str, ...], "Plugin"] = {}


def _map_command_to_plugin(plugin: "Plugin") -> None:
    """建立命令与插件的映射"""
    for matcher in plugin.matcher:
        command_handler = next(
            filter(
                lambda x: isinstance(x.call, (CommandRule, ShellCommandRule)),
                matcher.rule.checkers,
            ),
            None,
        )
        if not command_handler:
            continue

        command = cast("CommandRule | ShellCommandRule", command_handler.call)
        for cmd in command.cmds:
            _commands[cmd] = plugin


def _is_supported_adapter(bot: "Bot", metadata: "PluginMetadata") -> bool:
    if metadata.supported_adapters is None:
        return True
    supported_adapters = metadata.get_supported_adapters()
    if not supported_adapters:
        return False
    return any(isinstance(bot.adapter, adapter) for adapter in supported_adapters)


def _is_supported_type(metadata: "PluginMetadata") -> bool:
    type_ = metadata.type
    if type_ is None:
        return True
    return type_ == "application"


def is_supported(bot: "Bot", plugin: "Plugin") -> bool:
    if plugin.metadata is None:
        return False
    if plugin.metadata.name in plugin_config.help_ignored_plugins:
        return False
    if not _is_supported_type(plugin.metadata):
        return False
    return _is_supported_adapter(bot, plugin.metadata)


def get_plugins() -> dict[str, "Plugin"]:
    global _plugins  # noqa: PLW0603

    if _plugins is None:
        plugins = filter(lambda x: x.metadata is not None, get_loaded_plugins())
        _plugins = {x.metadata.name: x for x in plugins}  # type: ignore[union-attr]
        for plugin in _plugins.values():
            _map_command_to_plugin(plugin)

    return _plugins


def get_supported_plugins(bot: "Bot") -> list["Plugin"]:
    """获取所有受支持的根插件（按名称排序）。"""
    return sorted(
        (
            plugin
            for plugin in get_plugins().values()
            if plugin.parent_plugin is None
            and is_supported(bot, plugin)
            and plugin.matcher
        ),
        key=lambda x: x.metadata.name,  # type: ignore[union-attr]
    )


def format_plugin_list(bot: "Bot") -> str:
    """生成带序号的插件列表。"""
    plugins = get_supported_plugins(bot)
    if not plugins:
        return "当前没有可用的插件。"

    lines = ["📖 插件列表："]
    for i, plugin in enumerate(plugins, 1):
        meta = plugin.metadata
        lines.append(f"{i}. {meta.name} — {meta.description}")  # type: ignore[union-attr]
    lines.append(
        "\n💬 直接发送序号查看详细帮助 · 输入 0 退出\n"
        "⚠️ 请勿 @ 机器人或回复这条消息；@ 会产生通知，回复消息机器人无法继续处理。"
    )
    return "\n".join(lines)


def get_plugin_help_by_index(bot: "Bot", index: int) -> str | None:
    """根据序号获取插件详细帮助。"""
    plugins = get_supported_plugins(bot)
    if index < 1 or index > len(plugins):
        return None

    plugin = plugins[index - 1]
    return _format_plugin_detail(bot, plugin)


def get_plugin_help_by_name(bot: "Bot", name: str) -> str | None:
    """根据名称或命令获取插件详细帮助。"""
    plugins = get_plugins()

    plugin = plugins.get(name)
    if not plugin:
        for sep in global_config.command_sep:
            plugin = _commands.get(tuple(name.split(sep)))
            if plugin:
                break
    if not plugin or not is_supported(bot, plugin):
        return None

    return _format_plugin_detail(bot, plugin)


def _format_plugin_detail(bot: "Bot", plugin: "Plugin") -> str:
    metadata = cast("PluginMetadata", plugin.metadata)

    sub_plugins = [p for p in plugin.sub_plugins if is_supported(bot, p)]
    sub_desc = "\n".join(
        sorted(f" ↳ {x.metadata.name} — {x.metadata.description}" for x in sub_plugins)  # type: ignore[union-attr]
    )

    parts = [f"📖 {metadata.name}"]
    if metadata.usage:
        parts.append(metadata.usage)
    if sub_desc:
        parts.append(f"子插件：\n{sub_desc}")

    return "\n\n".join(parts)
