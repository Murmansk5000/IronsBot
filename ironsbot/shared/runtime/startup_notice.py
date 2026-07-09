# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class StartupNoticePart:
    subscription_key: str
    action_name: str
    message: str


@dataclass(frozen=True, slots=True)
class StartupNoticeProvider:
    subscription_key: str
    action_name: str
    get_message: Callable[[], str | None]


_startup_notice_providers: dict[str, StartupNoticeProvider] = {}


def register_startup_notice_provider(
    name: str,
    *,
    subscription_key: str,
    action_name: str,
    get_message: Callable[[], str | None],
) -> None:
    _startup_notice_providers[name] = StartupNoticeProvider(
        subscription_key=subscription_key,
        action_name=action_name,
        get_message=get_message,
    )


def startup_notice_parts() -> list[StartupNoticePart]:
    parts: list[StartupNoticePart] = []
    for provider in _startup_notice_providers.values():
        message = provider.get_message()
        if not message:
            continue
        parts.append(
            StartupNoticePart(
                subscription_key=provider.subscription_key,
                action_name=provider.action_name,
                message=message,
            )
        )
    return parts
