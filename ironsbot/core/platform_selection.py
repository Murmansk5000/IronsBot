# SPDX-License-Identifier: MIT
"""Deterministic outbound-platform selection for mixed QQ deployments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OutboundPlatform(str, Enum):
    NONE = "none"
    ONEBOT = "onebot"
    QQ_OFFICIAL = "qq_official"


@dataclass(frozen=True, slots=True)
class OutboundPlatformSelection:
    """Freeze platform precedence before adapters and plugins are composed."""

    platform: OutboundPlatform
    official_account_aliases: tuple[str, ...] = ()
    onebot_enabled: bool = True
    onebot_send_messages: bool = True

    @classmethod
    def resolve(
        cls,
        *,
        official_account_aliases: tuple[str, ...],
        onebot_enabled: bool,
        onebot_send_messages: bool,
    ) -> OutboundPlatformSelection:
        if official_account_aliases:
            platform = OutboundPlatform.QQ_OFFICIAL
        elif onebot_enabled and onebot_send_messages:
            platform = OutboundPlatform.ONEBOT
        else:
            platform = OutboundPlatform.NONE
        return cls(
            platform,
            official_account_aliases,
            onebot_enabled,
            onebot_send_messages,
        )

    @property
    def official_active(self) -> bool:
        return self.platform is OutboundPlatform.QQ_OFFICIAL

    @property
    def onebot_outbound_enabled(self) -> bool:
        return self.platform is OutboundPlatform.ONEBOT

    @property
    def onebot_message_handling_enabled(self) -> bool:
        return self.onebot_outbound_enabled
