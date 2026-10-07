# SPDX-License-Identifier: MIT
"""Shared exact-first matching for command names and domain references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Literal, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

T = TypeVar("T")
MatchKind = Literal["exact", "partial", "none"]


@dataclass(frozen=True, slots=True)
class MatchResult(Generic[T]):
    kind: MatchKind = "none"
    matches: tuple[T, ...] = ()


@dataclass(frozen=True, slots=True)
class TextMatchRule:
    normalize: Callable[[str], str]

    def key(self, text: str) -> str:
        return self.normalize(text)

    def matches(self, text: str, candidate: str) -> bool:
        key = self.key(text)
        return bool(key) and key == self.key(candidate)

    def matches_any(self, text: str, candidates: Iterable[str]) -> bool:
        key = self.key(text)
        return bool(key) and any(key == self.key(candidate) for candidate in candidates)

    def select(
        self,
        text: str,
        candidates: Iterable[T],
        *,
        names: Callable[[T], Iterable[str]],
        allow_partial: bool = True,
    ) -> MatchResult[T]:
        key = self.key(text)
        if not key:
            return MatchResult()
        exact: list[T] = []
        partial: list[T] = []
        for candidate in candidates:
            keys = tuple(self.key(name) for name in names(candidate))
            if key in keys:
                exact.append(candidate)
            elif allow_partial and any(key in name for name in keys):
                partial.append(candidate)
        if exact:
            return MatchResult("exact", tuple(exact))
        return MatchResult("partial", tuple(partial)) if partial else MatchResult()

    def contains_pattern(self, text: str) -> str:
        """Escape LIKE metacharacters so partial searches use literal input."""
        key = self.key(text)
        escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"
