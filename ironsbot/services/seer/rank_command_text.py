# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared normalization for rank-command suffix spellings."""

from __future__ import annotations

from ironsbot.core.commands import normalize_command_text

_RANK_SUFFIXES = ("排行榜", "排行")


def normalize_rank_command_text(text: str) -> str:
    """Normalize accepted rank suffixes to the parser's canonical ``榜``."""

    command = normalize_command_text(text)
    for suffix in _RANK_SUFFIXES:
        if command.endswith(suffix):
            return command.removesuffix(suffix) + "榜"
    return command
