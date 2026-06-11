# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_COMMAND_PREFIXES = ("/",)


def normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


def strip_command_prefix(
    text: str,
    prefixes: Iterable[str] = DEFAULT_COMMAND_PREFIXES,
) -> str | None:
    stripped = text.strip()
    for prefix in prefixes:
        if prefix and stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def command_text_matches(text: str, commands: Iterable[str]) -> bool:
    normalized = normalize_command_text(text)
    return normalized in {
        normalize_command_text(command)
        for command in commands
    }


def render_text(text: str) -> str:
    return text.replace("\\n", "\n")
