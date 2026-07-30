# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.selection import (
    HELP_SELECTION_FOOTER,
    SelectionMenuSection,
    format_selection_menu,
)
from ironsbot.runtime.feature_policy import event_is_feature_visible_in_help
from ironsbot.runtime.onebot_context import command_context

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.plugins import PluginDefinition

HELP_ENTRIES_KEY = "_help_entries"
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
HELP_INTERACTION_TITLES = {
    "conversation": "按提示继续",
    "passive": "被动触发",
    "automatic": "自动响应",
}


@dataclass(frozen=True, slots=True)
class HelpMenuEntry:
    key: str
    name: str
    description: str
    group: str
    order: int
    notes: tuple[str, ...]


class MissingHelpEntryError(ValueError):
    @classmethod
    def for_plugin(cls, plugin_id: str) -> MissingHelpEntryError:
        return cls(f"plugin has no help entry: {plugin_id}")


def entry_from_definition(definition: PluginDefinition) -> HelpMenuEntry:
    help_entry = definition.help
    if help_entry is None:
        raise MissingHelpEntryError.for_plugin(definition.id)
    return HelpMenuEntry(
        key=definition.id,
        name=help_entry.name,
        description=help_entry.description,
        group=help_entry.group,
        order=help_entry.order,
        notes=help_entry.notes,
    )


def entry_sort_key(entry: HelpMenuEntry) -> tuple[int, int, str]:
    group_index = (
        HELP_GROUP_ORDER.index(entry.group)
        if entry.group in HELP_GROUP_ORDER
        else len(HELP_GROUP_ORDER)
    )
    return (group_index, entry.order, entry.name)


def visible_help_entries(
    definitions: tuple[PluginDefinition, ...],
    event: MessageEvent,
    *,
    features: FeatureService,
    commands: CommandCatalog,
    ignored_plugins: tuple[str, ...],
) -> list[HelpMenuEntry]:
    entries: list[HelpMenuEntry] = []
    seen_names: set[str] = set()
    ignored_names = set(ignored_plugins)

    for definition in definitions:
        help_entry = definition.help
        if help_entry is None:
            continue
        if (
            definition.id in ignored_names
            or help_entry.name in ignored_names
            or help_entry.name in seen_names
        ):
            continue
        visible = help_entry.visible
        if visible is not None:
            if not visible(event):
                continue
        elif definition.commands:
            if not commands.available_for_context(
                command_context(event),
                features,
                plugin_id=definition.id,
                ignored_plugins=ignored_plugins,
            ):
                continue
        elif not any(
            event_is_feature_visible_in_help(features, event, feature.value)
            for feature in definition.features
        ):
            continue

        entries.append(entry_from_definition(definition))
        seen_names.add(help_entry.name)

    return sorted(entries, key=entry_sort_key)


def format_plugin_list(entries: list[HelpMenuEntry]) -> str:
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
            "⚠️ 请直接发送指令；回复机器人消息不会触发功能。"
        ),
    )


def format_plugin_detail(
    entry: HelpMenuEntry,
    event: MessageEvent,
    features: FeatureService,
    commands: CommandCatalog,
    *,
    ignored_plugins: tuple[str, ...],
) -> str:
    available = commands.available_for_context(
        command_context(event),
        features,
        plugin_id=entry.key,
        ignored_plugins=ignored_plugins,
    )
    lines = [f"📖 {entry.name}"]
    if entry.notes:
        lines.extend(("", *entry.notes))
    if not available:
        lines.extend(("", "暂无可直接输入的命令。"))
        return "\n".join(lines)

    for interaction in ("direct", "conversation", "passive", "automatic"):
        commands_for_interaction = tuple(
            command for command in available if command.interaction == interaction
        )
        if not commands_for_interaction:
            continue
        if interaction != "direct":
            lines.extend(("", f"【{HELP_INTERACTION_TITLES[interaction]}】"))

        current_section = ""
        for command in commands_for_interaction:
            if command.section != current_section:
                lines.extend(("", f"【{command.section}】"))
                current_section = command.section
            lines.append(f"{' / '.join(command.examples)} — {command.description}")
    return "\n".join(lines)
