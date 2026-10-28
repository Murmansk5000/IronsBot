# SPDX-License-Identifier: MIT
"""Expand configuration-only text variables without evaluating expressions."""

from __future__ import annotations

import re

_REFERENCE = re.compile(r"\$\{([^{}]*)\}")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def expand_message_variables(
    variables: dict[str, str], messages: list[list[str]]
) -> tuple[dict[str, str], list[list[str]]]:
    resolved: dict[str, str] = {}
    visiting: set[str] = set()

    def resolve(name: str) -> str:
        if name not in variables:
            message = f"unknown messaging variable: {name}"
            raise ValueError(message)
        if name in visiting:
            message = f"cyclic messaging variable: {name}"
            raise ValueError(message)
        if name not in resolved:
            visiting.add(name)
            resolved[name] = expand(variables[name])
            visiting.remove(name)
        return resolved[name]

    def expand(text: str) -> str:
        return _REFERENCE.sub(lambda match: resolve(match[1]), text)

    for name in variables:
        if not _NAME.fullmatch(name):
            message = f"invalid messaging variable name: {name}"
            raise ValueError(message)
        resolve(name)
    expanded = [[expand(text).strip() for text in sequence] for sequence in messages]
    if any(not text for sequence in expanded for text in sequence):
        message = "expanded message must not be empty"
        raise ValueError(message)
    return resolved, expanded
