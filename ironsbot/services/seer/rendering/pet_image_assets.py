# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable pet-head and type-icon assets shared by Seer renderers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PetImageAssets:
    """Data-URI assets prepared before a pet-oriented presentation starts."""

    pet_heads: tuple[tuple[int, str], ...]
    type_icons: tuple[tuple[int, str], ...]

    @property
    def pet_head_by_resource_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.pet_heads))

    @property
    def type_icon_by_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.type_icons))
