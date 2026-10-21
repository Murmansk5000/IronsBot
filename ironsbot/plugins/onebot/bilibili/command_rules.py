# SPDX-License-Identifier: MIT
"""Adapt OneBot events to the shared Bilibili command contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent

    from ironsbot.core.feature_policy import FeatureService


def matches_bilibili_command(
    command_id: str, features: FeatureService, event: MessageEvent
) -> bool:
    context = message_input_context(event)
    command_context = command_context_from_input(context)
    contract = next(c for c in bilibili_command_contracts() if c.id == command_id)
    return contract.is_executable(
        command_context, features
    ) and contract.matches_direct_input(command_context, context.text)
