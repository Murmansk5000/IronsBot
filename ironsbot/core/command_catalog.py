# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.commands import command_text_matches
from ironsbot.core.platform import is_supported_message_actor

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef

CommandScope = Literal["group", "private", "both"]
CommandAudience = Literal["regular", "group_manager", "superuser"]
CommandInteraction = Literal["direct", "conversation", "passive", "automatic"]
CommandHelpLevel = Literal["brief", "full"]
CommandVisibility = Callable[["CommandContext"], bool]


class CommandFeaturePolicy(Protocol):
    def is_actor_superuser(self, actor: ActorRef) -> bool: ...

    def conversation_has_feature(
        self,
        conversation: ConversationRef,
        feature: str,
    ) -> bool: ...

    def is_actor_feature_allowed(
        self,
        actor: ActorRef,
        feature: str,
    ) -> bool: ...

    def is_feature_allowed(
        self,
        actor: ActorRef,
        conversation: ConversationRef,
        feature: str,
    ) -> bool: ...


class CommandCatalogError(ValueError):
    @classmethod
    def already_loaded(cls) -> CommandCatalogError:
        return cls("command catalog is already loaded")

    @classmethod
    def empty_id(cls) -> CommandCatalogError:
        return cls("invalid command contract: id must not be empty")

    @classmethod
    def empty_plugin_id(cls) -> CommandCatalogError:
        return cls("invalid command contract: plugin_id must not be empty")

    @classmethod
    def empty_section(cls) -> CommandCatalogError:
        return cls("invalid command contract: section must not be empty")

    @classmethod
    def requires_examples(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command contract: {command_id!r} requires examples")

    @classmethod
    def invalid_routing_alias(cls, command_id: str) -> CommandCatalogError:
        return cls(
            f"invalid command contract: {command_id!r} has an empty routing alias"
        )

    @classmethod
    def requires_description(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command contract: {command_id!r} requires a description")

    @classmethod
    def invalid_scope(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command contract: {command_id!r} has invalid scope")

    @classmethod
    def invalid_audience(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command contract: {command_id!r} has invalid audience")

    @classmethod
    def private_group_manager(cls, command_id: str) -> CommandCatalogError:
        return cls(
            "invalid command contract: "
            f"group manager command {command_id!r} cannot be private-only"
        )

    @classmethod
    def empty_features_any(cls, command_id: str) -> CommandCatalogError:
        return cls(
            f"invalid command contract: {command_id!r} has an empty feature id"
        )

    @classmethod
    def invalid_interaction(cls, command_id: str) -> CommandCatalogError:
        return cls(
            f"invalid command contract: {command_id!r} has invalid interaction"
        )

    @classmethod
    def invalid_help_level(cls, command_id: str) -> CommandCatalogError:
        return cls(f"invalid command contract: {command_id!r} has invalid help level")

    @classmethod
    def unknown_registered_help_ids(
        cls,
        command_ids: Iterable[str],
    ) -> CommandCatalogError:
        return cls(
            "matchers reference unknown command contract ids: "
            + ", ".join(sorted(command_ids))
        )

    @classmethod
    def undocumented_direct_commands(
        cls,
        command_ids: Iterable[str],
    ) -> CommandCatalogError:
        return cls(
            "direct command contracts have no matcher registration: "
            + ", ".join(sorted(command_ids))
        )

    @classmethod
    def unclassified_matchers(cls, labels: Iterable[str]) -> CommandCatalogError:
        return cls(
            "command matchers have no help ids or explicit exemption: "
            + ", ".join(sorted(labels))
        )


@dataclass(frozen=True, slots=True)
class CommandContext:
    actor: ActorRef
    conversation: ConversationRef
    group_role: str | None = None
    member_mentions: tuple[ActorRef, ...] = ()

    @property
    def is_group(self) -> bool:
        return self.conversation.kind == "group"

    @property
    def has_member_mentions(self) -> bool:
        return bool(self.member_mentions)


CommandInputMatcher = Callable[[str, CommandContext], bool]
_Parsed = TypeVar("_Parsed")


def normalized_command_input_matcher(commands: Iterable[str]) -> CommandInputMatcher:
    """Opt into the same whitespace/case grammar used by a domain command rule."""
    names = tuple(commands)
    return lambda text, _context: command_text_matches(text, names)


def parsed_command_input_matcher(
    parser: Callable[[str], _Parsed | None],
    *,
    accepts: Callable[[_Parsed], bool] | None = None,
) -> CommandInputMatcher:
    """Adapt a pure domain parser without executing its command or guessing syntax."""

    def matches(text: str, _context: CommandContext) -> bool:
        parsed = parser(text)
        return parsed is not None and (accepts is None or accepts(parsed))

    return matches


@dataclass(frozen=True, slots=True)
class CommandAccess:
    """One allowed command audience and conversation scope."""

    scope: CommandScope = "both"
    audience: CommandAudience = "regular"
    features_any: tuple[str, ...] = ()
    features_all: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.scope not in {"group", "private", "both"}:
            raise CommandCatalogError.invalid_scope("access")
        if self.audience not in {"regular", "group_manager", "superuser"}:
            raise CommandCatalogError.invalid_audience("access")
        if self.audience == "group_manager" and self.scope == "private":
            raise CommandCatalogError.private_group_manager("access")
        if any(
            not feature.strip() for feature in (*self.features_any, *self.features_all)
        ):
            raise CommandCatalogError.empty_features_any("access")

    def is_available(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
    ) -> bool:
        if not _scope_matches(context, self.scope):
            return False
        if self.features_any and not any(
            _feature_is_allowed(features, context, feature)
            for feature in self.features_any
        ):
            return False
        if any(
            not _feature_is_allowed(features, context, feature)
            for feature in self.features_all
        ):
            return False
        if self.audience == "group_manager":
            return context.is_group and (
                context.group_role in GROUP_MANAGER_ROLES
                or features.is_actor_superuser(context.actor)
            )
        return self.audience != "superuser" or features.is_actor_superuser(
            context.actor
        )


@dataclass(frozen=True, slots=True)
class CommandContract:
    """One documented user input, shared by help and poke hints."""

    id: str
    plugin_id: str
    section: str
    examples: tuple[str, ...]
    description: str
    routing_aliases: tuple[str, ...] = ()
    routing_matcher: CommandInputMatcher | None = None
    features_any: tuple[str, ...] = ()
    features_all: tuple[str, ...] = ()
    access: tuple[CommandAccess, ...] = (CommandAccess(),)
    interaction: CommandInteraction = "direct"
    help_level: CommandHelpLevel = "full"
    notes: tuple[str, ...] = ()
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
        _validate_routing_aliases(self.id, self.routing_aliases)
        if not self.description.strip():
            raise CommandCatalogError.requires_description(self.id)
        if any(
            not feature.strip() for feature in (*self.features_any, *self.features_all)
        ):
            raise CommandCatalogError.empty_features_any(self.id)
        if not self.access:
            raise CommandCatalogError.invalid_scope(self.id)
        if self.interaction not in {"direct", "conversation", "passive", "automatic"}:
            raise CommandCatalogError.invalid_interaction(self.id)
        if self.help_level not in {"brief", "full"}:
            raise CommandCatalogError.invalid_help_level(self.id)

    def is_available(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
    ) -> bool:
        if not any(rule.is_available(context, features) for rule in self.access):
            return False
        if self.features_any and not any(
            _feature_is_allowed(features, context, feature)
            for feature in self.features_any
        ):
            return False
        if any(
            not _feature_is_allowed(features, context, feature)
            for feature in self.features_all
        ):
            return False
        return self.visible is None or self.visible(context)

    def poke_text(self) -> str:
        return f"发送“{self.examples[0]}”{self.description}。"

    def matches_direct_input(self, context: CommandContext, text: str) -> bool:
        """Return whether this command explicitly owns one direct input.

        Parameterized input remains opt-in through ``routing_matcher``. This
        keeps AI fallback from claiming a command without letting broad
        natural-language examples become implicit prefixes.
        """

        if self.interaction != "direct":
            return False
        if not text.strip():
            return False
        if self.routing_matcher is not None:
            return self.routing_matcher(text, context)
        return any(
            text == value
            for value in (*self.examples, *self.routing_aliases)
            if "<" not in value and ">" not in value
        )


class CommandContribution(Protocol):
    """The minimal plugin contribution shape needed by the command catalog."""

    @property
    def id(self) -> str: ...

    @property
    def commands(self) -> tuple[CommandContract, ...]: ...


def _validate_routing_aliases(command_id: str, aliases: tuple[str, ...]) -> None:
    if any(not alias.strip() for alias in aliases):
        raise CommandCatalogError.invalid_routing_alias(command_id)


def commands_from_rows(
    plugin_id: str,
    section: str,
    feature: str | None,
    rows: tuple[tuple[str, tuple[str, ...], str, dict[str, Any]], ...],
) -> tuple[CommandContract, ...]:
    """Build command contracts from concise plugin-owned command rows."""

    contracts = []
    for command_id, examples, description, raw_options in rows:
        options = dict(raw_options)
        command_features = options.pop(
            "features_any",
            (feature,) if feature is not None else (),
        )
        command_features_all = options.pop("features_all", ())
        access = options.pop("access", (CommandAccess(),))
        contracts.append(
            CommandContract(
                id=command_id,
                plugin_id=plugin_id,
                section=section,
                examples=examples,
                description=description,
                features_any=command_features,
                features_all=command_features_all,
                access=access,
                **options,
            )
        )
    return tuple(contracts)


def _scope_matches(context: CommandContext, scope: CommandScope) -> bool:
    if not is_supported_message_actor(context.actor, context.conversation):
        return False
    if scope == "both":
        return True
    if scope == "group":
        return context.is_group
    return context.conversation.kind == "private"


def _feature_is_allowed(
    features: CommandFeaturePolicy,
    context: CommandContext,
    feature: str,
) -> bool:
    if context.is_group:
        # Group help and poke hints describe the features enabled for the
        # whole group, rather than a superuser's execution bypass.
        return features.conversation_has_feature(
            context.conversation,
            feature,
        ) and features.is_feature_allowed(
            context.actor,
            context.conversation,
            feature,
        )
    return features.is_feature_allowed(context.actor, context.conversation, feature)


@dataclass(slots=True)
class CommandCatalog:
    """Validated command descriptions for the active plugin registry."""

    _commands: tuple[CommandContract, ...] = field(default=(), init=False)
    _loaded: bool = field(default=False, init=False)

    def load(
        self,
        definitions: Iterable[CommandContribution],
        *,
        known_features: Iterable[str] = (),
    ) -> None:
        if self._loaded:
            raise CommandCatalogError.already_loaded()
        definitions = tuple(definitions)
        plugin_ids = {definition.id for definition in definitions}
        commands = tuple(
            command for definition in definitions for command in definition.commands
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
                "duplicate command contract ids: " + ", ".join(duplicate_ids)
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
                "command contracts reference unknown plugins: "
                + ", ".join(invalid_plugins)
            )
        known_feature_set = set(known_features)
        invalid_features = sorted(
            {
                feature
                for command in commands
                for feature in (
                    *command.features_any,
                    *command.features_all,
                    *(
                        feature
                        for access in command.access
                        for feature in (*access.features_any, *access.features_all)
                    ),
                )
                if feature not in known_feature_set
            }
        )
        if invalid_features:
            raise CommandCatalogError(
                "command contracts reference unknown features: "
                + ", ".join(invalid_features)
            )
        self._commands = commands
        self._loaded = True

    def available_for_context(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str | None = None,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandContract, ...]:
        ignored = set(ignored_plugins)
        return tuple(
            command
            for command in self._commands
            if (plugin_id is None or command.plugin_id == plugin_id)
            if command.plugin_id not in ignored
            if command.is_available(context, features)
        )

    @property
    def command_ids(self) -> frozenset[str]:
        return frozenset(command.id for command in self._commands)

    @property
    def direct_command_ids(self) -> frozenset[str]:
        return frozenset(
            command.id for command in self._commands if command.interaction == "direct"
        )

    def validate_matcher_registrations(
        self,
        *,
        help_ids: Iterable[str],
        unclassified_labels: Iterable[str] = (),
    ) -> None:
        unclassified = tuple(unclassified_labels)
        if unclassified:
            raise CommandCatalogError.unclassified_matchers(unclassified)
        registered_ids = frozenset(help_ids)
        unknown = registered_ids - self.command_ids
        if unknown:
            raise CommandCatalogError.unknown_registered_help_ids(unknown)
        missing = self.direct_command_ids - registered_ids
        if missing:
            raise CommandCatalogError.undocumented_direct_commands(missing)

    def poke_candidates_for_context(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        *,
        ignored_plugins: Iterable[str] = (),
    ) -> tuple[CommandContract, ...]:
        return tuple(
            command
            for command in self.available_for_context(
                context,
                features,
                ignored_plugins=ignored_plugins,
            )
            if command.show_in_poke
        )

    def claims_direct_input(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        text: str,
        *,
        ignored_plugins: Iterable[str] = (),
    ) -> bool:
        """Whether an available direct command owns this exact input spelling.

        Literal aliases preserve their required prefix. Parameterized grammar
        is delegated to registered domain parsers; the catalog never invents
        implicit prefixes or resolves message targets on its own.
        """

        return any(
            command.matches_direct_input(context, text)
            for command in self.available_for_context(
                context,
                features,
                ignored_plugins=ignored_plugins,
            )
        )

    def recognizes_direct_input(
        self,
        context: CommandContext,
        text: str,
        *,
        ignored_plugins: Iterable[str] = (),
    ) -> bool:
        """Whether a command owns an input before feature or audience checks."""

        ignored = set(ignored_plugins)
        return any(
            command.plugin_id not in ignored
            and any(_scope_matches(context, access.scope) for access in command.access)
            and command.matches_direct_input(context, text)
            for command in self._commands
        )

    def format_for_context(
        self,
        context: CommandContext,
        features: CommandFeaturePolicy,
        *,
        plugin_id: str,
        ignored_plugins: Iterable[str] = (),
    ) -> str:
        available = self.available_for_context(
            context,
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
