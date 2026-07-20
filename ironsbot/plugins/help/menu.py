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
from ironsbot.services.seer.query_usage import build_seer_query_usage_message

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.features import FeatureService
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


@dataclass(frozen=True, slots=True)
class HelpMenuEntry:
    key: str
    name: str
    description: str
    usage: str
    group: str
    order: int


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
        usage=help_entry.usage or "暂无详细帮助。",
        group=help_entry.group,
        order=help_entry.order,
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
    event: Event,
    *,
    features: FeatureService,
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
    event: Event,
    features: FeatureService,
) -> str:
    if entry.key == "seer_query":
        usage = build_seer_query_usage_message(
            lambda feature: event_is_feature_visible_in_help(features, event, feature)
        )
        return f"📖 {entry.name}\n\n{usage}"

    return f"📖 {entry.name}\n\n{entry.usage}"
