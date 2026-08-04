# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.plugin import PluginMetadata

    from ironsbot.core.features import Feature
    from ironsbot.runtime.commands import CommandDescriptor
    from ironsbot.runtime.matchers import MatcherRegistry

HookResult: TypeAlias = Awaitable[None] | None
LifecycleHook: TypeAlias = Callable[[], HookResult]
BotLifecycleHook: TypeAlias = Callable[["Bot"], HookResult]
NamedLifecycleHook: TypeAlias = tuple[str, LifecycleHook]
NamedBotLifecycleHook: TypeAlias = tuple[str, BotLifecycleHook]
HelpVisibility: TypeAlias = Callable[["Event"], bool]
PluginInstall: TypeAlias = Callable[["MatcherRegistry"], None]


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


class PluginContributionError(ValueError):
    """Raised when declarative plugin contributions cannot be composed."""

    @classmethod
    def duplicate_ids(cls, plugin_ids: tuple[str, ...]) -> PluginContributionError:
        return cls("duplicate plugin contribution ids: " + ", ".join(plugin_ids))


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


@contextmanager
def scoped_plugin_install_context(
    *,
    settings: Any,
    resources: Any,
    scheduler: Any,
) -> Iterator[PluginInstallContext]:
    """Expose composition dependencies while `nonebot.load_from_toml()` runs."""

    context = PluginInstallContext(
        settings=settings,
        resources=resources,
        scheduler=scheduler,
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


def validate_plugin_contributions(
    contributions: tuple[PluginContribution, ...],
) -> tuple[PluginContribution, ...]:
    """Validate the minimal invariants shared by every plugin-loading path."""

    ids = tuple(contribution.id for contribution in contributions)
    duplicate_ids = tuple(sorted({item for item in ids if ids.count(item) > 1}))
    if duplicate_ids:
        raise PluginContributionError.duplicate_ids(duplicate_ids)
    return contributions
