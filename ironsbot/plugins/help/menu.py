# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot import get_loaded_plugins

from ironsbot.config.loader import get_app_config
from ironsbot.plugin_catalog import help_layout_for_module
from ironsbot.services.seer.query_usage import build_seer_query_usage_message
from ironsbot.shared.selection_menu import (
    HELP_SELECTION_FOOTER,
    SelectionMenuSection,
    format_selection_menu,
)

from .visibility import plugin_visible_for_event

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event
    from nonebot.plugin import Plugin, PluginMetadata

    from ironsbot.config.models.runtime import HelpConfig

HELP_ENTRIES_KEY = "_help_entries"
HELP_PLUGIN_NAME = "help"
HELP_GROUP_ORDER = (
    "core",
    "seer",
    "message",
    "ai",
    "admin",
    "other",
)
HELP_GROUP_TITLES = {
    "core": "基础",
    "seer": "赛尔查询",
    "message": "消息与推送",
    "ai": "AI",
    "admin": "管理工具",
    "other": "其他",
}
@dataclass(frozen=True, slots=True)
class HelpEntry:
    key: str
    name: str
    description: str
    usage: str
    group: str
    order: int


def get_help_config() -> HelpConfig:
    return get_app_config().runtime.help


def plugin_module_name(plugin: "Plugin") -> str:
    return str(getattr(plugin, "module_name", "") or getattr(plugin, "name", ""))


def plugin_key(plugin: "Plugin") -> str:
    return plugin_module_name(plugin) or cast("PluginMetadata", plugin.metadata).name


def ignored_plugin_names() -> set[str]:
    return set(get_help_config().ignored_plugins)


def is_supported_adapter(bot: "Bot", metadata: PluginMetadata) -> bool:
    if metadata.supported_adapters is None:
        return True
    supported_adapters = metadata.get_supported_adapters()
    if not supported_adapters:
        return False
    return any(isinstance(bot.adapter, adapter) for adapter in supported_adapters)


def is_supported_type(metadata: PluginMetadata) -> bool:
    return metadata.type is None or metadata.type == "application"


def entry_from_plugin(plugin: "Plugin") -> HelpEntry:
    metadata = cast("PluginMetadata", plugin.metadata)
    group, order = help_layout_for_module(plugin_module_name(plugin))
    return HelpEntry(
        key=plugin_key(plugin),
        name=metadata.name,
        description=metadata.description,
        usage=metadata.usage or "暂无详细帮助。",
        group=group,
        order=order,
    )


def entry_sort_key(entry: HelpEntry) -> tuple[int, int, str]:
    group_index = (
        HELP_GROUP_ORDER.index(entry.group)
        if entry.group in HELP_GROUP_ORDER
        else len(HELP_GROUP_ORDER)
    )
    return (group_index, entry.order, entry.name)


def visible_help_entries(bot: "Bot", event: "Event") -> list[HelpEntry]:
    entries: list[HelpEntry] = []
    seen_names: set[str] = set()
    ignored_names = ignored_plugin_names()

    plugins = sorted(
        get_loaded_plugins(),
        key=lambda plugin: (
            cast("PluginMetadata", plugin.metadata).name
            if plugin.metadata
            else ""
        ),
    )
    for plugin in plugins:
        metadata = plugin.metadata
        if metadata is None:
            continue
        if metadata.name in ignored_names or metadata.name in seen_names:
            continue
        if not is_supported_type(metadata) or not is_supported_adapter(bot, metadata):
            continue
        module_name = plugin_module_name(plugin)
        if not plugin_visible_for_event(metadata.name, module_name, event):
            continue

        entries.append(entry_from_plugin(plugin))
        seen_names.add(metadata.name)

    return sorted(entries, key=entry_sort_key)


def format_plugin_list(entries: list[HelpEntry]) -> str:
    if not entries:
        return "当前会话没有可用的功能。"

    sections: list[SelectionMenuSection] = []
    current_group = ""
    current_items: list[str] = []

    for entry in entries:
        group = entry.group
        if group != current_group:
            if current_items:
                sections.append(
                    SelectionMenuSection(
                        title=HELP_GROUP_TITLES.get(current_group, "其他"),
                        items=tuple(current_items),
                    )
                )
            current_group = group
            current_items = []
        current_items.append(f"{entry.name} — {entry.description}")

    if current_items:
        sections.append(
            SelectionMenuSection(
                title=HELP_GROUP_TITLES.get(current_group, "其他"),
                items=tuple(current_items),
            )
        )

    return format_selection_menu(
        title="📖 可用功能：",
        items=tuple(sections),
        footer=(
            f"{HELP_SELECTION_FOOTER}\n"
            "⚠️ 请直接发送指令；回复机器人消息不会触发功能。\n"
            "🧩 此机器人无法查询精灵配置；没有收录配置图片，也没有人维护配置收集。"
        ),
    )


def format_plugin_detail(entry: HelpEntry, event: "Event") -> str:
    if entry.key.startswith("ironsbot.plugins.seer.query"):
        return f"📖 {entry.name}\n\n{build_seer_query_usage_message(event)}"

    return f"📖 {entry.name}\n\n{entry.usage}"


__all__ = [
    "HELP_ENTRIES_KEY",
    "HELP_GROUP_TITLES",
    "HELP_PLUGIN_NAME",
    "HelpEntry",
    "format_plugin_detail",
    "format_plugin_list",
    "visible_help_entries",
]
