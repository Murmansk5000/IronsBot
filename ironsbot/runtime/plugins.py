# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import Bot

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
class PluginDefinition:
    id: str
    features: frozenset[Feature] = frozenset()
    help: HelpEntry | None = None
    commands: tuple[CommandDescriptor, ...] = ()
    install: PluginInstall | None = None
    hooks: PluginHooks = PluginHooks()
