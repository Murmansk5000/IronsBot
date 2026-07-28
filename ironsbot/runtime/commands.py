# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from ironsbot.runtime.permissions import GROUP_MANAGER_ROLES

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.runtime.plugins import PluginDefinition

CommandScope = Literal["group", "private", "both"]
CommandAudience = Literal["regular", "group_manager", "superuser"]
CommandVisibility = Callable[["CommandContext"], bool]


class CommandFeaturePolicy(Protocol):
    def is_superuser(self, user_id: int) -> bool: ...

    def group_has_feature(self, group_id: int, feature: str) -> bool: ...

    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
        /,
    ) -> bool: ...

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool: ...


class CommandCatalogError(ValueError):
    @classmethod
    def already_loaded(cls) -> CommandCatalogError:
        return cls("command catalog is already loaded")

    @classmethod
    def empty_id(cls) -> CommandCatalogError:
        return cls("invalid command descriptor: id must not be empty")

    @classmethod
    def empty_plugin_id(cls) -> CommandCatalogError:
        return cls("invalid command descriptor: plugin_id must not be empty")

    @classmethod
    def empty_section(cls) -> CommandCatalogError:
        return cls("invalid command descriptor: section must not be empty")

    @classmethod
    def requires_examples(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command descriptor: {command_id!r} requires examples")

    @classmethod
    def requires_description(cls, command_id: str) -> CommandCatalogError:
        return cls(
            f"invalid command descriptor: {command_id!r} requires a description"
        )

    @classmethod
    def invalid_scope(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command descriptor: {command_id!r} has invalid scope")

    @classmethod
    def invalid_audience(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command descriptor: {command_id!r} has invalid audience")

    @classmethod
    def private_group_manager(cls, command_id: str) -> CommandCatalogError:
        return cls(
            "invalid command descriptor: "
            f"group manager command {command_id!r} cannot be private-only"
        )


@dataclass(frozen=True, slots=True)
class CommandContext:
    user_id: int
    group_id: int | None
    group_role: str | None = None

    @classmethod
    def from_event(cls, event: object) -> CommandContext:
        sender = getattr(event, "sender", None)
        role = getattr(sender, "role", None)
        return cls(
            user_id=int(cast("Any", event).user_id),
            group_id=(
                int(group_id)
                if (group_id := getattr(event, "group_id", None)) is not None
                else None
            ),
            group_role=str(role) if role is not None else None,
        )

    @property
    def is_group(self) -> bool:
        return self.group_id is not None


@dataclass(frozen=True, slots=True)
class CommandDescriptor:
    """One documented user input, shared by help and poke hints."""

    id: str
    plugin_id: str
    section: str
    examples: tuple[str, ...]
    description: str
    feature: str | None = None
    scope: CommandScope = "both"
    audience: CommandAudience = "regular"
    show_in_poke: bool = False
    visible: CommandVisibility | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise CommandCatalogError.empty_id()
        if not self.plugin_id.strip():
            raise CommandCatalogError.empty_plugin_id()
        if not self.section.strip():
            raise CommandCatalogError.empty_section()
        if not self.examples or any(not example.strip() for example in self.examples):
            raise CommandCatalogError.requires_examples(self.id)
        if not self.description.strip():
            raise CommandCatalogError.requires_description(self.id)
        if self.scope not in {"group", "private", "both"}:
            raise CommandCatalogError.invalid_scope(self.id)
        if self.audience not in {"regular", "group_manager", "superuser"}:
            raise CommandCatalogError.invalid_audience(self.id)
        if self.audience == "group_manager" and self.scope == "private":
            raise CommandCatalogError.private_group_manager(self.id)

    def is_available(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
    ) -> bool:
        if not _scope_matches(context, self.scope):
            return False
        if self.audience == "group_manager" and not (
            context.is_group
            and (
                context.group_role in GROUP_MANAGER_ROLES
                or features.is_superuser(context.user_id)
            )
        ):
            return False
        if self.audience == "superuser" and not features.is_superuser(
            context.user_id
        ):
            return False
        if self.feature is not None and not _feature_is_allowed(
            features, context, self.feature
        ):
            return False
        return self.visible is None or self.visible(context)

    def poke_text(self) -> str:
        return f"发送“{self.examples[0]}”{self.description}。"


def _scope_matches(context: CommandContext, scope: CommandScope) -> bool:
    if scope == "both":
        return True
    if scope == "group":
        return context.is_group
    return not context.is_group


def _feature_is_allowed(
    features: CommandFeaturePolicy,
    context: CommandContext,
    feature: str,
) -> bool:
    if context.group_id is not None:
        # Group help and poke hints describe the features enabled for the
        # whole group, rather than a superuser's execution bypass.
        return features.group_has_feature(
            context.group_id,
            feature,
        ) and features.is_group_feature_allowed(
            context.user_id,
            context.group_id,
            feature,
        )
    return features.is_private_feature_allowed(context.user_id, feature)


@dataclass(slots=True)
class CommandCatalog:
    """Validated command descriptions for the active plugin registry."""

    _commands: tuple[CommandDescriptor, ...] = field(default=(), init=False)
    _loaded: bool = field(default=False, init=False)

    def load(
        self,
        definitions: Iterable["PluginDefinition"],
        *,
        known_features: Iterable[str] = (),
    ) -> None:
        if self._loaded:
            raise CommandCatalogError.already_loaded()
        definitions = tuple(definitions)
        plugin_ids = {definition.id for definition in definitions}
        commands = tuple(
            command
            for definition in definitions
            for command in definition.commands
        )
        duplicate_ids = sorted(
            {
                command.id
                for command in commands
                if sum(other.id == command.id for other in commands) > 1
            }
        )
        if duplicate_ids:
            raise CommandCatalogError(
                "duplicate command descriptor ids: " + ", ".join(duplicate_ids)
            )
        invalid_plugins = sorted(
            {
                command.plugin_id
                for command in commands
                if command.plugin_id not in plugin_ids
            }
        )
        if invalid_plugins:
            raise CommandCatalogError(
                "command descriptors reference unknown plugins: "
                + ", ".join(invalid_plugins)
            )
        known_feature_set = set(known_features)
        invalid_features = sorted(
            {
                command.feature
                for command in commands
                if command.feature is not None
                if command.feature not in known_feature_set
            }
        )
        if invalid_features:
            raise CommandCatalogError(
                "command descriptors reference unknown features: "
                + ", ".join(invalid_features)
            )
        self._commands = commands
        self._loaded = True

    def available_for(
        self,
        event: object,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str | None = None,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandDescriptor, ...]:
        return self.available_for_context(
            CommandContext.from_event(event),
            features,
            plugin_id=plugin_id,
            ignored_plugins=ignored_plugins,
        )

    def available_for_context(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str | None = None,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandDescriptor, ...]:
        ignored = set(ignored_plugins)
        return tuple(
            command
            for command in self._commands
            if (plugin_id is None or command.plugin_id == plugin_id)
            if command.plugin_id not in ignored
            if command.is_available(context, features)
        )

    def available_for_plugin(
        self,
        event: object,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandDescriptor, ...]:
        return self.available_for(
            event,
            features,
            plugin_id=plugin_id,
            ignored_plugins=ignored_plugins,
        )

    def poke_candidates(
        self,
        event: object,
        features: CommandFeaturePolicy,
        *,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandDescriptor, ...]:
        return tuple(
            command
            for command in self.available_for(
                event,
                features,
                ignored_plugins=ignored_plugins,
            )
            if command.show_in_poke
        )

    def poke_candidates_for_context(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        *,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandDescriptor, ...]:
        return tuple(
            command
            for command in self.available_for_context(
                context,
                features,
                ignored_plugins=ignored_plugins,
            )
            if command.show_in_poke
        )

    def format_for(
        self,
        event: object,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str,
        ignored_plugins: Iterable[str] = (),
    ) -> str:
        available = self.available_for(
            event,
            features,
            plugin_id=plugin_id,
            ignored_plugins=ignored_plugins,
        )
        if not available:
            return "暂无可直接输入的命令。"

        lines: list[str] = []
        current_section = ""
        for command in available:
            if command.section != current_section:
                if lines:
                    lines.append("")
                lines.append(f"【{command.section}】")
                current_section = command.section
            lines.append(f"{' / '.join(command.examples)} — {command.description}")
        return "\n".join(lines)
