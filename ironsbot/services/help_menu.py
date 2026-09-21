# SPDX-License-Identifier: MIT
"""Platform-neutral interactive help menu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import (
    EXIT_SELECTION_LINE,
    HELP_SELECTION_FOOTER,
    SelectionMenuSection,
    format_selection_menu,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandCatalog, CommandContext
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.plugin_install import PluginContribution
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation

HELP_GROUP_ORDER = ("core", "seer", "message", "ai", "admin", "other")
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


def entry_from_definition(definition: PluginContribution) -> HelpMenuEntry:
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


def visible_help_entries(  # noqa: PLR0913 - explicit directory dependencies
    definitions: tuple[PluginContribution, ...],
    context: CommandContext,
    *,
    features: FeatureService,
    commands: CommandCatalog,
    ignored_plugins: tuple[str, ...],
    command_ids: frozenset[str] | None = None,
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
            if not visible(context):
                continue
        elif definition.commands:
            if not _available_commands(
                commands,
                context,
                features,
                plugin_id=definition.id,
                ignored_plugins=ignored_plugins,
                command_ids=command_ids,
            ):
                continue
        elif not any(
            _feature_is_visible(features, context, feature.value)
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
        if entry.group != current_group:
            if current_items:
                sections.append(
                    SelectionMenuSection(
                        title=HELP_GROUP_TITLES.get(current_group, "其他"),
                        items=tuple(current_items),
                    )
                )
            current_group = entry.group
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
            "⚠️ 可引用消息后直接发送指令；引用中的 @ 会被忽略。"
        ),
    )


def format_plugin_detail(  # noqa: PLR0913 - explicit directory dependencies
    entry: HelpMenuEntry,
    context: CommandContext,
    features: FeatureService,
    commands: CommandCatalog,
    *,
    ignored_plugins: tuple[str, ...],
    command_ids: frozenset[str] | None = None,
) -> str:
    available = _available_commands(
        commands,
        context,
        features,
        plugin_id=entry.key,
        ignored_plugins=ignored_plugins,
        command_ids=command_ids,
    )
    lines = [f"📖 {entry.name}"]
    if entry.notes:
        lines.extend(("", *entry.notes))
    if not available:
        lines.extend(("", "暂无可直接输入的命令。", "", EXIT_SELECTION_LINE))
        return "\n".join(lines)

    for interaction in ("direct", "conversation", "passive", "automatic"):
        matching = tuple(
            command for command in available if command.interaction == interaction
        )
        if not matching:
            continue
        if interaction != "direct":
            lines.extend(("", f"【{HELP_INTERACTION_TITLES[interaction]}】"))
        current_section = ""
        for command in matching:
            if command.section != current_section:
                lines.extend(("", f"【{command.section}】"))
                current_section = command.section
            lines.append(f"{' / '.join(command.examples)} — {command.description}")
    lines.extend(("", EXIT_SELECTION_LINE))
    return "\n".join(lines)


def build_portable_help_operation(  # noqa: PLR0913 - composition boundary
    definitions: tuple[PluginContribution, ...],
    commands: CommandCatalog,
    features: FeatureService,
    sessions: PortableQuerySessions,
    *,
    ignored_plugins: tuple[str, ...] = (),
    command_ids: frozenset[str] | None = None,
) -> PortableOperation:
    """Build one interactive help operation for every message platform."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        command_context = command_context_from_input(context)
        entries = visible_help_entries(
            definitions,
            command_context,
            features=features,
            commands=commands,
            ignored_plugins=ignored_plugins,
            command_ids=command_ids,
        )
        if not entries:
            return OutboundMessage.from_text("当前会话没有可用的功能。")

        async def select(
            entry: HelpMenuEntry,
            context: MessageInputContext,
        ) -> OutboundMessage:
            return OutboundMessage.from_text(
                format_plugin_detail(
                    entry,
                    command_context_from_input(context),
                    features,
                    commands,
                    ignored_plugins=ignored_plugins,
                    command_ids=command_ids,
                )
            )

        prompt = OutboundMessage.from_text(format_plugin_list(entries))
        return sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=tuple(entries),
                select=select,
                prompt=prompt,
                keep_open=True,
                exit_message="✅ 已退出帮助。",
            ),
        )

    return execute


def _available_commands(  # noqa: PLR0913 - mirrors catalog filtering contract
    commands: CommandCatalog,
    context: CommandContext,
    features: FeatureService,
    *,
    plugin_id: str | None = None,
    ignored_plugins: tuple[str, ...] = (),
    command_ids: frozenset[str] | None = None,
):
    available = commands.available_for_context(
        context,
        features,
        plugin_id=plugin_id,
        ignored_plugins=ignored_plugins,
    )
    if command_ids is None:
        return available
    return tuple(command for command in available if command.id in command_ids)


def _feature_is_visible(
    features: FeatureService,
    context: CommandContext,
    feature: str,
) -> bool:
    if context.is_group:
        return features.conversation_has_feature(context.conversation, feature)
    return features.is_feature_allowed(context.actor, context.conversation, feature)
