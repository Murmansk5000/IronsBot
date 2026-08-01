# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import Any, Literal, TypedDict

from typing_extensions import NotRequired


class MintMarkDict(TypedDict):
    id: int
    name: str
    desc: str
    icon: str
    skills: list[str]


class ActivationItemPriceDict(TypedDict):
    source_name: str
    item_quantity: int
    currency_item_id: int
    currency_name: str
    amount: int
    purchase_limit: int | None
    currency_icon: str | None


class ActivationItemDict(TypedDict):
    id: int
    name: str
    icon: str | None
    prices: list[ActivationItemPriceDict]


class SkillDict(TypedDict):
    id: int
    name: str
    type_id: int
    type_name: str
    category_id: int
    category_name: str
    power: int
    max_pp: int
    accuracy: int | Literal["必中"]
    crit_rate: float | None
    priority: int
    must_hit: bool
    info: str | None
    learning_level: int | None
    is_special: bool
    is_advanced: bool
    is_fifth: bool
    effects: list[dict[str, Any]]
    activation_item: ActivationItemDict | None
    friend_bonus: bool
    hide_effect_desc: str | None


class SoulmarkDict(TypedDict):
    id: int
    desc: str
    intensified: bool
    intensified_to_id: int | None
    is_adv: bool
    pve_effective: bool | None
    tags: list[str]
    icon_id: int | None
    icon_asset_url: str | None
    icon: str | None


class SpecialEffectDict(TypedDict):
    name: str
    desc: str | None
    sources: list[str]
    glossary_id: int | None
    status_id: int | None
    icon: str | None
    color: NotRequired[str]


class PartnerItemDict(TypedDict):
    id: int
    name: str
    quantity: int
    icon: str | None
    prices: list[ActivationItemPriceDict]


class PartnerSkillDict(TypedDict):
    id: int
    name: str
    activation_item: PartnerItemDict | None


class PetPartnerDict(TypedDict):
    name: str
    cost_item: PartnerItemDict
    skill: PartnerSkillDict | None
