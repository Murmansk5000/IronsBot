# SPDX-License-Identifier: GPL-3.0-or-later
"""Immutable data contracts for the pet information render pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class PetStatsSnapshot:
    """Six displayed pet stats, already rounded by the data repository."""

    atk: int
    def_: int
    sp_atk: int
    sp_def: int
    spd: int
    hp: int

    @property
    def total(self) -> int:
        return self.atk + self.def_ + self.sp_atk + self.sp_def + self.spd + self.hp


@dataclass(frozen=True, slots=True)
class PetCoreSnapshot:
    id: int
    name: str
    resource_id: int
    gender_id: int
    type_id: int
    type_name: str
    introduction: str


@dataclass(frozen=True, slots=True)
class PetItemPriceSnapshot:
    source_name: str
    item_name: str
    item_quantity: int
    currency_item_id: int
    currency_name: str
    amount: int
    purchase_limit: int | None


@dataclass(frozen=True, slots=True)
class PetItemSnapshot:
    id: int
    name: str
    quantity: int
    prices: tuple[PetItemPriceSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class PetSkillEffectSnapshot:
    effect_id: int
    analyze_info: str | None
    info: str | None


@dataclass(frozen=True, slots=True)
class PetSkillSnapshot:
    id: int
    name: str
    type_id: int
    type_name: str
    category_id: int
    category_name: str
    power: int
    max_pp: int
    accuracy: int
    crit_rate: float | None
    priority: int
    must_hit: bool
    info: str | None
    learning_level: int | None
    is_special: bool
    is_advanced: bool
    is_fifth: bool
    effects: tuple[PetSkillEffectSnapshot, ...]
    friend_effects: tuple[PetSkillEffectSnapshot, ...]
    activation_item_id: int | None
    hide_effect_description: str | None


@dataclass(frozen=True, slots=True)
class PetSoulmarkSnapshot:
    id: int
    desc: str
    analyze_desc: str | None
    formatting_adjustment: str | None
    intensified: bool
    intensified_to_id: int | None
    is_adv: bool
    pve_effective: bool | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PetSoulmarkDisplayAddition:
    """A published soulmark display fact not represented by a raw soulmark row."""

    id: int
    desc: str
    analyze_desc: str | None
    formatting_adjustment: str | None
    intensified: bool
    intensified_to_id: int | None
    is_adv: bool
    pve_effective: bool | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PetMintmarkSnapshot:
    id: int
    name: str
    description: str
    skill_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PetPartnerSkillSnapshot:
    id: int
    name: str
    activation_item: PetItemSnapshot | None


@dataclass(frozen=True, slots=True)
class PetPartnerSnapshot:
    group_id: int
    name: str
    cost_item: PetItemSnapshot
    before_description: str
    after_description: str
    skill: PetPartnerSkillSnapshot | None


@dataclass(frozen=True, slots=True)
class PetSpecialEffectView:
    """One published special effect ready for presentation."""

    name: str
    description: str | None
    glossary_id: int | None
    status_id: int | None
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SoulmarkIconAsset:
    """A pre-rendered soulmark icon published with SeerAPI data."""

    icon_id: int
    png: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class PetDerivedDisplayData:
    """Published facts consumed without renderer-side inference."""

    special_effects: tuple[PetSpecialEffectView, ...]
    soulmark_display_order: tuple[tuple[int, int], ...]
    soulmark_icons: tuple[tuple[int, SoulmarkIconAsset], ...]
    soulmark_display_additions: tuple[PetSoulmarkDisplayAddition, ...] = ()
    soulmark_display_kinds: tuple[tuple[int, str], ...] = ()

    @property
    def soulmark_order_by_id(self) -> Mapping[int, int]:
        return dict(self.soulmark_display_order)

    @property
    def soulmark_icon_by_id(self) -> Mapping[int, SoulmarkIconAsset]:
        return dict(self.soulmark_icons)

    @property
    def soulmark_display_kind_by_id(self) -> Mapping[int, str]:
        return dict(self.soulmark_display_kinds)


@dataclass(frozen=True, slots=True)
class PetInfoSnapshot:
    """All database-derived inputs required to render one pet information card."""

    pet: PetCoreSnapshot
    base_stats: PetStatsSnapshot
    advance_stats: PetStatsSnapshot | None
    skills: tuple[PetSkillSnapshot, ...]
    soulmarks: tuple[PetSoulmarkSnapshot, ...]
    activation_items: tuple[PetItemSnapshot, ...]
    partner: PetPartnerSnapshot | None
    skill_mintmarks: tuple[PetMintmarkSnapshot, ...]
    display: PetDerivedDisplayData
    rich_texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PetInfoAssets:
    """All binary assets needed by the pure pet-info presenter."""

    gender_icon: bytes
    pet_head: bytes
    pet_body: bytes
    type_icons: tuple[tuple[int | str, bytes], ...]
    mintmark_icons: tuple[tuple[int, bytes], ...]
    item_icons: tuple[tuple[int, bytes], ...]
    special_effect_icons: tuple[tuple[int, bytes], ...]

    @property
    def type_icon_by_id(self) -> Mapping[int | str, bytes]:
        return dict(self.type_icons)

    @property
    def mintmark_icon_by_id(self) -> Mapping[int, bytes]:
        return dict(self.mintmark_icons)

    @property
    def item_icon_by_id(self) -> Mapping[int, bytes]:
        return dict(self.item_icons)

    @property
    def special_effect_icon_by_status_id(self) -> Mapping[int, bytes]:
        return dict(self.special_effect_icons)


@dataclass(frozen=True, slots=True)
class PetInfoRenderDocument:
    """Template-ready immutable document produced from a snapshot and assets."""

    template_name: str
    templates: Mapping[str, object]
