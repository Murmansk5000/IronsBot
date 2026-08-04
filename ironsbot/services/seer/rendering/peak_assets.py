# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable image assets shared by the peak rendering documents."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PeakRenderAssets:
    """Data-URI assets prepared before peak presentation starts."""

    pet_heads: tuple[tuple[int, str], ...]
    type_icons: tuple[tuple[int, str], ...]

    @property
    def pet_head_by_resource_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.pet_heads))

    @property
    def type_icon_by_id(self) -> Mapping[int, str]:
        return MappingProxyType(dict(self.type_icons))
