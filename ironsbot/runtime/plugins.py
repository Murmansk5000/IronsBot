# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

    from ironsbot.core.features import Feature
    from ironsbot.runtime.matchers import MatcherRegistry

AsyncHook: TypeAlias = Callable[[], Awaitable[None]]
BotHook: TypeAlias = Callable[["Bot"], Awaitable[None]]
Installer: TypeAlias = Callable[[], None]
NamedAsyncHook: TypeAlias = tuple[str, AsyncHook]
NamedBotHook: TypeAlias = tuple[str, BotHook]
NamedInstaller: TypeAlias = tuple[str, Installer]
HelpVisibility = Literal["default", "always", "hidden"]
PluginInstall: TypeAlias = Callable[["MatcherRegistry"], None]


@dataclass(frozen=True, slots=True)
class HelpEntry:
    name: str
    description: str
    usage: str
    group: str
    order: int
    visibility: HelpVisibility = "default"


@dataclass(frozen=True, slots=True)
class PluginHooks:
    installers: tuple[NamedInstaller, ...] = ()
    startup: tuple[NamedAsyncHook, ...] = ()
    shutdown: tuple[NamedAsyncHook, ...] = ()
    first_bot_connect: tuple[NamedBotHook, ...] = ()
    bot_connect: tuple[NamedBotHook, ...] = ()
    bot_disconnect: tuple[NamedBotHook, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginDefinition:
    id: str
    features: frozenset[Feature]
    help: HelpEntry | None
    install: PluginInstall
    hooks: PluginHooks = PluginHooks()


__all__ = [
    "AsyncHook",
    "BotHook",
    "HelpEntry",
    "HelpVisibility",
    "Installer",
    "NamedAsyncHook",
    "NamedBotHook",
    "NamedInstaller",
    "PluginDefinition",
    "PluginHooks",
    "PluginInstall",
]
