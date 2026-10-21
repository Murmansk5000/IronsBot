# SPDX-License-Identifier: MIT
"""Execution-time authorization shared by platform operation adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input

if TYPE_CHECKING:
    from ironsbot.core.command_catalog import CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation


def authorized_operation(
    operation: PortableOperation, contract: CommandContract, features: FeatureService
) -> PortableOperation:
    async def execute(text: str, context: MessageInputContext):
        message = context.message
        if features.is_message_blocked(message.actor, message.conversation):
            return None
        if not contract.is_executable(command_context_from_input(context), features):
            return None
        return await operation(text, context)

    return execute
