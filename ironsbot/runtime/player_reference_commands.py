# SPDX-License-Identifier: MIT
"""Parser-aware command ownership for player-reference inputs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ironsbot.core.commands import normalize_command_text

if TYPE_CHECKING:
    from ironsbot.core.player_references import PlayerReferenceLookup
    from ironsbot.runtime.commands import CommandContext

PlayerReferenceInputMatcher = Callable[[str, "CommandContext"], bool]


def player_reference_input_matcher(
    prefixes: tuple[str, ...],
    reference_lookup: PlayerReferenceLookup,
    *,
    accept_empty: bool = True,
) -> PlayerReferenceInputMatcher:
    """Build command ownership matching for numeric or configured player input.

    A catalog needs to keep recognized player commands out of private AI
    fallback without treating ordinary prose such as ``米米号是什么`` as a
    failed player command. Numeric references are claimed so the command can
    return its own validation error; aliases are claimed only when visible in
    the current conversation.
    """

    normalized_prefixes = tuple(
        sorted(
            {
                normalized
                for prefix in prefixes
                if (normalized := normalize_command_text(prefix))
            },
            key=len,
            reverse=True,
        )
    )

    def matches(text: str, context: CommandContext) -> bool:
        normalized_text = normalize_command_text(text)
        prefix = next(
            (
                candidate
                for candidate in normalized_prefixes
                if normalized_text.startswith(candidate)
            ),
            None,
        )
        if prefix is None:
            return False
        reference = normalized_text[len(prefix) :]
        if not reference:
            return accept_empty
        return reference.isdecimal() or (
            reference_lookup(reference, context.conversation) is not None
        )

    return matches
