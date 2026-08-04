# SPDX-License-Identifier: MIT
"""Typed, platform-neutral aliases for domain-owned entities.

Each domain owns its own alias source and normalization rule. This module owns
only the reusable lookup result shape, so callers can distinguish no match from
an ambiguous match without inventing local dictionaries or sentinels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


T = TypeVar("T")


class AliasError(ValueError):
    """Raised when an alias cannot be stored with the supplied normalizer."""


@dataclass(frozen=True, slots=True)
class AliasMatch(Generic[T]):
    """One configured alias and the domain value it resolves to."""

    alias: str
    value: T


@dataclass(frozen=True, slots=True)
class AliasResolution(Generic[T]):
    """The complete result of looking up one user-supplied reference."""

    reference: str
    matches: tuple[AliasMatch[T], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.matches

    @property
    def is_unique(self) -> bool:
        return len(self.matches) == 1

    @property
    def is_ambiguous(self) -> bool:
        return len(self.matches) > 1

    @property
    def unique_value(self) -> T | None:
        return self.matches[0].value if self.is_unique else None


class AliasLookup(Protocol[T]):
    """A domain-owned source that resolves one normalized alias reference."""

    def resolve_alias(self, reference: object) -> AliasResolution[T]: ...


class AliasIndex(Generic[T]):
    """Small in-memory implementation for aliases already loaded by a domain."""

    def __init__(self, normalizer: Callable[[str], str]) -> None:
        self._normalizer = normalizer
        self._matches: dict[str, list[AliasMatch[T]]] = {}

    @classmethod
    def from_pairs(
        cls,
        pairs: Iterable[tuple[str, T]],
        *,
        normalizer: Callable[[str], str],
    ) -> AliasIndex[T]:
        index = cls(normalizer)
        for alias, value in pairs:
            index.add(alias, value)
        return index

    def add(self, alias: str, value: T) -> None:
        normalized = self._normalize(alias)
        self._matches.setdefault(normalized, []).append(AliasMatch(alias, value))

    def resolve_alias(self, reference: object) -> AliasResolution[T]:
        text = str(reference).strip()
        if not text:
            return AliasResolution(reference=text)
        normalized = self._normalize(text, required=False)
        if not normalized:
            return AliasResolution(reference=text)
        return AliasResolution(
            reference=text,
            matches=tuple(self._matches.get(normalized, ())),
        )

    def _normalize(self, value: str, *, required: bool = True) -> str:
        normalized = self._normalizer(value)
        if normalized:
            return normalized
        if required:
            msg = "alias normalizer must return a nonempty value"
            raise AliasError(msg)
        return ""
