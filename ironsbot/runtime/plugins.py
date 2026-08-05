# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

from ironsbot.core.features import Feature

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.plugin import PluginMetadata

    from ironsbot.runtime.commands import CommandDescriptor
    from ironsbot.runtime.matchers import MatcherFactory

HookResult: TypeAlias = Awaitable[None] | None
LifecycleHook: TypeAlias = Callable[[], HookResult]
BotLifecycleHook: TypeAlias = Callable[["Bot"], HookResult]
NamedLifecycleHook: TypeAlias = tuple[str, LifecycleHook]
NamedBotLifecycleHook: TypeAlias = tuple[str, BotLifecycleHook]
HelpVisibility: TypeAlias = Callable[["Event"], bool]
PluginInstall: TypeAlias = Callable[["MatcherFactory"], None]


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

    This is deliberately not plugin discovery metadata. Standard NoneBot TOML
    remains responsible for discovering top-level plugins; the scoped install
    context collects these contributions after their modules are loaded.
    """

    id: str
    features: frozenset[Feature] = frozenset()
    help: HelpEntry | None = None
    commands: tuple[CommandDescriptor, ...] = ()
    install: PluginInstall | None = None
    hooks: PluginHooks = PluginHooks()


@dataclass(frozen=True, slots=True)
class LoadedPluginContribution:
    """A contribution paired with its NoneBot top-level plugin metadata."""

    metadata: PluginMetadata
    contribution: PluginContribution


class PluginInstallContextError(RuntimeError):
    """Raised when a plugin tries to access scoped install dependencies late."""

    @classmethod
    def unavailable(cls) -> PluginInstallContextError:
        return cls(
            "plugin install context is only available while NoneBot loads plugins"
        )


class PluginExtensionContextError(RuntimeError):
    """Raised when an extension requests a context it was not declared for."""

    @classmethod
    def unavailable(cls, extension_id: str) -> PluginExtensionContextError:
        return cls(f"plugin extension context is unavailable: {extension_id}")


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


_INSTALL_CONTEXT: ContextVar[PluginInstallContext | None] = ContextVar(
    "ironsbot_plugin_install_context",
    default=None,
)


@dataclass(slots=True)
class PluginInstallContext:
    """Explicit dependencies available only while NoneBot loads local plugins.

    The context exists to bridge declarative NoneBot module loading and the
    already-built application resources. It is reset immediately after module
    loading, so it cannot become a runtime service locator.
    """

    settings: Any
    resources: Any
    scheduler: Any
    extension_contexts: Mapping[str, object]
    _loaded: list[LoadedPluginContribution]

    def contribute(
        self,
        metadata: PluginMetadata,
        *contributions: PluginContribution,
    ) -> None:
        self._loaded.extend(
            LoadedPluginContribution(metadata=metadata, contribution=contribution)
            for contribution in contributions
        )

    @property
    def contributions(self) -> tuple[PluginContribution, ...]:
        return tuple(item.contribution for item in self._loaded)

    @property
    def loaded_contributions(self) -> tuple[LoadedPluginContribution, ...]:
        return tuple(self._loaded)

    def extension_context(self, extension_id: str) -> object:
        """Return the narrow contract declared for one external extension."""

        try:
            return self.extension_contexts[extension_id]
        except KeyError as error:
            raise PluginExtensionContextError.unavailable(extension_id) from error


@contextmanager
def scoped_plugin_install_context(
    *,
    settings: Any,
    resources: Any,
    scheduler: Any,
    extension_contexts: Mapping[str, object] | None = None,
) -> Iterator[PluginInstallContext]:
    """Expose composition dependencies while `nonebot.load_from_toml()` runs."""

    context = PluginInstallContext(
        settings=settings,
        resources=resources,
        scheduler=scheduler,
        extension_contexts=extension_contexts or {},
        _loaded=[],
    )
    token = _INSTALL_CONTEXT.set(context)
    try:
        yield context
    finally:
        _INSTALL_CONTEXT.reset(token)


def current_plugin_install_context() -> PluginInstallContext:
    """Return the active install context or fail outside the loading window."""

    context = _INSTALL_CONTEXT.get()
    if context is None:
        raise PluginInstallContextError.unavailable()
    return context


def active_plugin_install_context() -> PluginInstallContext | None:
    """Return the scoped install context when a top-level plugin is loading."""

    return _INSTALL_CONTEXT.get()


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
