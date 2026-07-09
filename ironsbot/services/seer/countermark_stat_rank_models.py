# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seerapi_models import MintmarkORM
    from seerapi_models.common import SixAttributes

@dataclass(frozen=True, slots=True)
class StatSpec:
    key: str
    title: str
    components: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CountermarkStatRankCommand:
    stat: StatSpec | None
    scope: str
    angle_count: int | None = None


@dataclass(frozen=True, slots=True)
class CountermarkStatRankItem:
    mintmark: MintmarkORM
    attrs: SixAttributes
    value: float
    total: float
    class_name: str
    angle_count: int | None
