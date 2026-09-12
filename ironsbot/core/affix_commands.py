# SPDX-License-Identifier: MIT
"""Literal prefix/suffix grammar, independent of event and command frameworks."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AffixArgument:
    prefix: str
    suffix: str
    argument: str


AffixParser = Callable[[str], AffixArgument | None]


@dataclass(frozen=True, slots=True)
class AffixCommand:
    prefixes: tuple[str, ...]
    suffixes: tuple[str, ...]
    ignorecase: bool = True
    reject: Callable[[str], bool] | None = None

    def __call__(self, text: str) -> AffixArgument | None:
        flags = re.IGNORECASE if self.ignorecase else 0
        prefix = (
            re.match(
                "^(?:" + "|".join(map(re.escape, self.prefixes)) + ")", text, flags
            )
            if self.prefixes
            else None
        )
        suffix = (
            re.search(
                "(?:" + "|".join(map(re.escape, self.suffixes)) + ")$", text, flags
            )
            if self.suffixes
            else None
        )
        if not prefix and not suffix:
            return None
        if self.reject is not None and self.reject(text):
            return None
        start = prefix.end() if prefix else 0
        # A command matching both ends must not consume an overlapping suffix twice.
        end = suffix.start() if suffix and suffix.start() >= start else len(text)
        return AffixArgument(
            prefix.group() if prefix else "",
            suffix.group() if suffix else "",
            text[start:end],
        )
