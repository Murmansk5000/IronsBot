# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from ironsbot.core.features import Feature

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContext, CommandContract
    from ironsbot.core.platform import BotAccountRef

HookResult: TypeAlias = Awaitable[None] | None
LifecycleHook: TypeAlias = Callable[[], HookResult]
BotLifecycleHook: TypeAlias = Callable[["BotAccountRef"], HookResult]
NamedLifecycleHook: TypeAlias = tuple[str, LifecycleHook]
NamedBotLifecycleHook: TypeAlias = tuple[str, BotLifecycleHook]
# Help visibility consumes normalized identity and conversation facts so every
# adapter presents the same feature directory.
HelpVisibility: TypeAlias = Callable[["CommandContext"], bool]


@dataclass(frozen=True, slots=True)
class HelpEntry:
    name: str
    description: str
    group: str
    order: int
    visible: HelpVisibility | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginHooks:
    startup: tuple[NamedLifecycleHook, ...] = ()
    shutdown: tuple[NamedLifecycleHook, ...] = ()
    first_bot_connect: tuple[NamedBotLifecycleHook, ...] = ()
    bot_connect: tuple[NamedBotLifecycleHook, ...] = ()
    bot_disconnect: tuple[NamedBotLifecycleHook, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginContribution:
    """One plugin's explicit runtime contributions during installation.

    Composition invokes built-in and private factories explicitly. This value
    declares business ownership, commands and lifecycle hooks, not discovery
    metadata or a framework installation callback.
    """

    id: str
    features: frozenset[Feature] = frozenset()
    help: HelpEntry | None = None
    commands: tuple[CommandContract, ...] = ()
    hooks: PluginHooks = PluginHooks()


class PluginContributionError(ValueError):
    """Raised when declarative plugin contributions cannot be composed."""

    @classmethod
    def duplicate_ids(cls, plugin_ids: tuple[str, ...]) -> PluginContributionError:
        return cls("duplicate plugin contribution ids: " + ", ".join(plugin_ids))

    @classmethod
    def missing_feature_owners(
        cls,
        features: tuple[Feature, ...],
    ) -> PluginContributionError:
        return cls(
            "features have no owning plugin contribution: "
            + ", ".join(feature.value for feature in features)
        )


class PluginContributionCatalogError(RuntimeError):
    @classmethod
    def already_loaded(cls) -> PluginContributionCatalogError:
        return cls("plugin contribution catalog is already loaded")


OPTIONAL_PRIVATE_FEATURES = frozenset({Feature.PLAYER_LINEUP_PRIVATE})


class PluginContributionCatalog:
    """Read-only view of the contributions frozen by application configuration."""

    def __init__(self) -> None:
        self._contributions: tuple[PluginContribution, ...] = ()
        self._loaded = False

    def load(self, contributions: tuple[PluginContribution, ...]) -> None:
        if self._loaded:
            raise PluginContributionCatalogError.already_loaded()
        self._contributions = contributions
        self._loaded = True

    @property
    def contributions(self) -> tuple[PluginContribution, ...]:
        return self._contributions


def validate_plugin_contributions(
    contributions: tuple[PluginContribution, ...],
    *,
    required_features: frozenset[Feature] | None = None,
) -> tuple[PluginContribution, ...]:
    """Validate the minimal invariants shared by every plugin-loading path."""

    ids = tuple(contribution.id for contribution in contributions)
    duplicate_ids = tuple(sorted({item for item in ids if ids.count(item) > 1}))
    if duplicate_ids:
        raise PluginContributionError.duplicate_ids(duplicate_ids)
    if required_features is None:
        return contributions
    owned_features = {
        feature for contribution in contributions for feature in contribution.features
    }
    missing_features = tuple(
        sorted(
            required_features - owned_features - OPTIONAL_PRIVATE_FEATURES,
            key=lambda feature: feature.value,
        )
    )
    if missing_features:
        raise PluginContributionError.missing_feature_owners(missing_features)
    return contributions
