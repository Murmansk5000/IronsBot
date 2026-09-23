# SPDX-License-Identifier: MIT
"""Capture a command identity, never its caller's permission decision."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import command_context_from_input

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_types import MenuAccess


def menu_access_resolver(
    catalog: CommandCatalog, features: FeatureService
) -> Callable[[MessageInputContext], MenuAccess]:
    def resolve(source: MessageInputContext) -> MenuAccess:
        original = command_context_from_input(source)
        texts = (source.text.strip(), source.text.strip().removeprefix("/").strip())
        command_ids = frozenset(
            command.id
            for command in catalog.executable_for_context(original, features)
            if any(command.matches_direct_input(original, text) for text in texts)
        )

        def allowed(responder: MessageInputContext) -> bool:
            return any(
                command.id in command_ids
                for command in catalog.executable_for_context(
                    command_context_from_input(responder), features
                )
            )

        return allowed

    return resolve


def explicit_command_resolver(
    catalog: CommandCatalog, features: FeatureService
) -> Callable[[MessageInputContext], bool]:
    def owns(context: MessageInputContext) -> bool:
        command_context = command_context_from_input(context)
        texts = (context.text.strip(), context.text.strip().removeprefix("/").strip())
        return any(
            command.matches_direct_input(command_context, text)
            for command in catalog.executable_for_context(command_context, features)
            for text in texts
        )

    return owns
