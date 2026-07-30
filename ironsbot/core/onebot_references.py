# SPDX-License-Identifier: MIT
"""Strict resolution for configured OneBot user and group references."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated

from pydantic import BeforeValidator

from ironsbot.core.commands import csv_items, json_array


class OneBotReferenceError(ValueError):
    """Raised when a configured OneBot target cannot be resolved."""

    @classmethod
    def empty_alias(cls, location: str) -> OneBotReferenceError:
        return cls(f"{location} contains an empty alias")

    @classmethod
    def numeric_alias(cls, location: str, alias: str) -> OneBotReferenceError:
        return cls(f"{location}.{alias} must not use a numeric alias")

    @classmethod
    def invalid_alias_target(
        cls,
        location: str,
        alias: str,
    ) -> OneBotReferenceError:
        return cls(f"{location}.{alias} must map to a positive integer ID")

    @classmethod
    def empty_reference(
        cls,
        location: str,
        kind: str,
    ) -> OneBotReferenceError:
        return cls(f"{location} contains an empty {kind} ref")

    @classmethod
    def unknown_alias(
        cls,
        location: str,
        kind: str,
        value: str,
    ) -> OneBotReferenceError:
        return cls(f"{location} references unknown {kind} alias: {value}")

    @classmethod
    def invalid_reference(
        cls,
        location: str,
        kind: str,
    ) -> OneBotReferenceError:
        return cls(f"{location} must be a positive {kind} ID or known alias")


def onebot_reference_list(value: object) -> list[str | int]:
    """Preserve numeric IDs while normalizing aliases for later resolution."""

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        raw_items = (
            json_array(text, name="OneBot reference list")
            if text.startswith("[")
            else csv_items(text)
        )
        if not raw_items:
            raw_items = ("",)
    elif isinstance(value, int):
        raw_items = (value,)
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        raw_items = (value,)

    result: list[str | int] = []
    for raw_item in raw_items:
        item: str | int
        if isinstance(raw_item, int) and not isinstance(raw_item, bool):
            item = raw_item
        else:
            item = str(raw_item).strip()
        if item not in result:
            result.append(item)
    return result


OneBotReferenceList = Annotated[list[str | int], BeforeValidator(onebot_reference_list)]


def normalize_alias_mapping(
    value: Mapping[str, object],
    *,
    location: str,
) -> dict[str, int]:
    """Normalize a user/group alias map without allowing numeric aliases."""

    normalized: dict[str, int] = {}
    for raw_alias, raw_target_id in value.items():
        alias = str(raw_alias).strip()
        if not alias:
            raise OneBotReferenceError.empty_alias(location)
        if alias.isdecimal():
            raise OneBotReferenceError.numeric_alias(location, alias)
        try:
            target_id = int(str(raw_target_id).strip())
        except (TypeError, ValueError) as exc:
            raise OneBotReferenceError.invalid_alias_target(
                location,
                alias,
            ) from exc
        if target_id <= 0:
            raise OneBotReferenceError.invalid_alias_target(location, alias)
        normalized[alias] = target_id
    return normalized


@dataclass(frozen=True, slots=True)
class OneBotReferenceResolver:
    """Resolve configured user/group aliases and numeric OneBot IDs."""

    group_aliases: Mapping[str, int]
    user_aliases: Mapping[str, int]

    def resolve_group(self, reference: object, *, location: str) -> int:
        return self._resolve(
            reference,
            aliases=self.group_aliases,
            kind="group",
            location=location,
        )

    def resolve_user(self, reference: object, *, location: str) -> int:
        return self._resolve(
            reference,
            aliases=self.user_aliases,
            kind="user",
            location=location,
        )

    def resolve_groups(
        self,
        references: Iterable[object],
        *,
        location: str,
    ) -> list[int]:
        return self._resolve_many(
            references,
            resolve=self.resolve_group,
            location=location,
        )

    def resolve_users(
        self,
        references: Iterable[object],
        *,
        location: str,
    ) -> list[int]:
        return self._resolve_many(
            references,
            resolve=self.resolve_user,
            location=location,
        )

    @staticmethod
    def _resolve_many(
        references: Iterable[object],
        *,
        resolve: Callable[..., int],
        location: str,
    ) -> list[int]:
        resolved: list[int] = []
        for index, reference in enumerate(references):
            target_id = resolve(reference, location=f"{location}[{index}]")
            if target_id not in resolved:
                resolved.append(target_id)
        return resolved

    @staticmethod
    def _resolve(
        reference: object,
        *,
        aliases: Mapping[str, int],
        kind: str,
        location: str,
    ) -> int:
        value = str(reference).strip()
        if not value:
            raise OneBotReferenceError.empty_reference(location, kind)
        if value in aliases:
            return aliases[value]
        if not value.isdecimal():
            raise OneBotReferenceError.unknown_alias(location, kind, value)
        target_id = int(value)
        if target_id <= 0:
            raise OneBotReferenceError.invalid_reference(location, kind)
        return target_id
