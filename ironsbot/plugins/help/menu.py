# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot import get_loaded_plugins

from ironsbot.config.loader import get_app_config
from ironsbot.services.seer.query_usage import build_seer_query_usage_message
from ironsbot.shared.features.visibility import plugin_visible_for_event
from ironsbot.shared.selection_menu import (
    HELP_SELECTION_FOOTER,
    SelectionMenuSection,
    format_selection_menu,
)

if TYPE_CHECKING:
    from nonebot.adapters import Bot, Event
    from nonebot.plugin import Plugin, PluginMetadata

    from ironsbot.config.models.runtime import HelpConfig

DEFAULT_IGNORED_PLUGINS = [
    "发图",
    "HTTP 缓存客户端",
    "赛尔号数据",
    "赛尔号信息查询",
    "AI @ 提示拦截",
    "超级管理员优先级",
    "定时重启",
]
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
HELP_ENTRY_ORDER = {
    "帮助": ("core", 10),
    "关于": ("core", 20),
    "赛尔号查询": ("seer", 10),
    "榜单": ("seer", 20),
    "图片发送": ("seer", 30),
    "活动结束提醒": ("message", 10),
    "B站动态": ("message", 20),
    "文本发送": ("message", 30),
    "会议回复": ("message", 40),
    "AI聊天": ("ai", 10),
    "AI意图分析": ("ai", 20),
    "战队推荐": ("seer", 40),
    "战队资源订阅": ("seer", 50),
    "战队审核入群提示": ("seer", 60),
    "开服查询": ("seer", 70),
    "数据库同步": ("admin", 20),
    "自定义无头登录": ("admin", 30),
}


@dataclass(frozen=True, slots=True)
class HelpEntry:
    key: str
    name: str
    description: str
    usage: str


def get_help_config() -> HelpConfig:
    return get_app_config().runtime.help


def plugin_module_name(plugin: "Plugin") -> str:
    return str(getattr(plugin, "module_name", "") or getattr(plugin, "name", ""))


def plugin_key(plugin: "Plugin") -> str:
    return plugin_module_name(plugin) or cast("PluginMetadata", plugin.metadata).name


def ignored_plugin_names() -> set[str]:
    return {
        *DEFAULT_IGNORED_PLUGINS,
        *get_help_config().ignored_plugins,
    }


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
    return HelpEntry(
        key=plugin_key(plugin),
        name=metadata.name,
        description=metadata.description,
        usage=metadata.usage or "暂无详细帮助。",
    )


def entry_sort_key(entry: HelpEntry) -> tuple[int, int, str]:
    group, order = HELP_ENTRY_ORDER.get(entry.name, ("other", 1000))
    group_index = (
        HELP_GROUP_ORDER.index(group)
        if group in HELP_GROUP_ORDER
        else len(HELP_GROUP_ORDER)
    )
    return (group_index, order, entry.name)


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
        group = HELP_ENTRY_ORDER.get(entry.name, ("other", 1000))[0]
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
    "HELP_ENTRY_ORDER",
    "HELP_GROUP_TITLES",
    "HELP_PLUGIN_NAME",
    "HelpEntry",
    "format_plugin_detail",
    "format_plugin_list",
    "visible_help_entries",
]
