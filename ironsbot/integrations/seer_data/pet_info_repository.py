# SPDX-License-Identifier: GPL-3.0-or-later
"""Database-backed snapshots for the pet information rendering pipeline."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from seerapi_models import MintmarkORM, PetORM
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from ironsbot.services.seer.rendering.pet_info_models import (
    PetCoreSnapshot,
    PetInfoSnapshot,
    PetItemPriceSnapshot,
    PetItemSnapshot,
    PetMintmarkSnapshot,
    PetPartnerSkillSnapshot,
    PetPartnerSnapshot,
    PetSkillEffectSnapshot,
    PetSkillSnapshot,
    PetSoulmarkSnapshot,
    PetStatsSnapshot,
)

from .pet_display_data import load_pet_derived_display_data
from .pet_soulmark_resolution import resolve_partner_upgraded_soulmark_ids

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)
ITEM_EXCHANGE_PRICE_TABLE = "item_exchange_price"
MAX_ITEM_EXCHANGE_PRICE_ROWS = 3
_LEGACY_CURRENCY_NAMES = {1726710: "共鸣锚点", 1726992: "共振晶体"}
_SPECIAL_SKILL_SHOP_SOURCE_KEY = "special_skill_shop"
_SPECIAL_SKILL_SHOP_SOURCE_NAME = "微光秘境"
_NORMALIZED_PARTNER_UPGRADE_SOURCE = (
    "ConfigPackage/partnerEffectUpgrade.bytes#normalized-v1"
)
_HIDDEN_SKILL_ID = 19002


class PetInfoRepository:
    """Load every database value required for one detached pet render snapshot."""

    def load(self, session: Session, pet_id: int) -> PetInfoSnapshot | None:
        pet = session.get(PetORM, pet_id)
        if pet is None:
            return None

        # Every relationship access happens before this method returns. The
        # caller can close its session before network or HTML work starts.
        skills = tuple(_snapshot_skill(link) for link in pet.skill_links)
        soulmarks = tuple(_snapshot_soulmark(soulmark) for soulmark in pet.soulmark)
        activation_items = _load_activation_items(session, pet.skill_links)
        partner = _load_partner(session, int(pet.id))
        skill_mintmarks = _load_skill_mintmarks(session, pet, skills)
        derived_display = load_pet_derived_display_data(
            session,
            pet_id=int(pet.id),
            soulmark_ids=(soulmark.id for soulmark in soulmarks),
        )
        return PetInfoSnapshot(
            pet=PetCoreSnapshot(
                id=int(pet.id),
                name=str(pet.name),
                resource_id=int(pet.resource_id),
                gender_id=int(pet.gender.id),
                type_id=int(pet.type.id),
                type_name=str(pet.type.name),
                introduction=(
                    str(pet.encyclopedia.introduction).strip()
                    if pet.encyclopedia is not None
                    else ""
                ),
            ),
            base_stats=_snapshot_stats(pet.base_stats),
            advance_stats=(
                _snapshot_stats(pet.advance.base_stats)
                if pet.advance is not None
                else None
            ),
            skills=skills,
            soulmarks=soulmarks,
            activation_items=activation_items,
            partner=partner,
            skill_mintmarks=skill_mintmarks,
            display=derived_display,
            rich_texts=_collect_rich_texts(skills, soulmarks),
            partner_upgraded_soulmark_ids=resolve_partner_upgraded_soulmark_ids(
                soulmarks,
                partner,
            ),
        )


def load_pet_info_snapshot(session: Session, pet_id: int) -> PetInfoSnapshot | None:
    """Compatibility-free repository entry point used by composition adapters."""
    return PetInfoRepository().load(session, pet_id)


def _snapshot_stats(stats: Any) -> PetStatsSnapshot:
    values = stats.to_model().round().model_dump()
    return PetStatsSnapshot(
        atk=int(values["atk"]),
        def_=int(values["def_"]),
        sp_atk=int(values["sp_atk"]),
        sp_def=int(values["sp_def"]),
        spd=int(values["spd"]),
        hp=int(values["hp"]),
    )


def _snapshot_skill(link: Any) -> PetSkillSnapshot:
    skill = link.skill
    return PetSkillSnapshot(
        id=int(skill.id),
        name=str(skill.name),
        type_id=int(skill.type.id),
        type_name=str(skill.type.name),
        category_id=int(skill.category.id),
        category_name=str(skill.category.name),
        power=int(skill.power),
        max_pp=int(skill.max_pp),
        accuracy=int(skill.accuracy),
        crit_rate=float(skill.crit_rate) if skill.crit_rate is not None else None,
        priority=int(skill.priority),
        must_hit=bool(skill.must_hit),
        info=str(skill.info) if skill.info is not None else None,
        learning_level=(
            int(link.learning_level) if link.learning_level is not None else None
        ),
        is_special=bool(link.is_special),
        is_advanced=bool(link.is_advanced),
        is_fifth=bool(link.is_fifth),
        effects=_snapshot_skill_effects(skill.skill_effect),
        friend_effects=_snapshot_skill_effects(skill.friend_skill_effect),
        activation_item_id=(
            int(link.skill_activation_item_id)
            if link.skill_activation_item_id is not None
            else None
        ),
        hide_effect_description=(
            str(skill.hide_effect.description)
            if skill.hide_effect is not None and skill.hide_effect.description
            else None
        ),
    )


def _snapshot_skill_effects(
    effects: Iterable[Any],
) -> tuple[PetSkillEffectSnapshot, ...]:
    return tuple(
        PetSkillEffectSnapshot(
            effect_id=int(effect.effect_id),
            analyze_info=(
                str(effect.analyze_info) if effect.analyze_info is not None else None
            ),
            info=str(effect.info) if effect.info is not None else None,
        )
        for effect in effects
    )


def _snapshot_soulmark(soulmark: Any) -> PetSoulmarkSnapshot:
    return PetSoulmarkSnapshot(
        id=int(soulmark.id),
        desc=str(soulmark.desc or ""),
        analyze_desc=(
            str(soulmark.analyze_desc) if soulmark.analyze_desc is not None else None
        ),
        formatting_adjustment=(
            str(soulmark.desc_formatting_adjustment)
            if soulmark.desc_formatting_adjustment is not None
            else None
        ),
        intensified=bool(soulmark.intensified),
        intensified_to_id=(
            int(soulmark.intensified_to_id)
            if soulmark.intensified_to_id is not None
            else None
        ),
        is_adv=bool(soulmark.is_adv),
        pve_effective=(
            bool(soulmark.pve_effective)
            if soulmark.pve_effective is not None
            else None
        ),
        tags=tuple(str(tag.name) for tag in soulmark.tag),
    )


def _collect_rich_texts(
    skills: Sequence[PetSkillSnapshot],
    soulmarks: Sequence[PetSoulmarkSnapshot],
) -> tuple[str, ...]:
    texts: list[str] = []
    for skill in skills:
        if skill.info:
            texts.append(skill.info)
        texts.extend(
            description
            for effect in (*skill.effects, *skill.friend_effects)
            if (description := effect.analyze_info or effect.info)
        )
        if skill.hide_effect_description:
            texts.append(skill.hide_effect_description)
    texts.extend(
        soulmark.analyze_desc for soulmark in soulmarks if soulmark.analyze_desc
    )
    return tuple(texts)


def _load_activation_items(
    session: Session,
    skill_links: Iterable[Any],
) -> tuple[PetItemSnapshot, ...]:
    items: dict[int, tuple[str, int]] = {}
    for link in skill_links:
        item_id = int(link.skill_activation_item_id or 0)
        if item_id <= 0:
            continue
        item = link.skill_activation_item
        if item is not None:
            items.setdefault(item_id, (str(item.name), 1))
        else:
            # Older data releases may expose only the activation item ID. Keep
            # it in the snapshot so the exchange-price table can supply its name.
            items.setdefault(item_id, ("", 1))

    prices_by_item = _load_item_exchange_prices(session, items)
    for item_id, prices in prices_by_item.items():
        name, quantity = items.get(item_id, ("", 1))
        if not name:
            name = next((price.item_name for price in prices if price.item_name), "")
            if name:
                items[item_id] = (name, quantity)

    return tuple(
        PetItemSnapshot(
            id=item_id,
            name=name,
            quantity=quantity,
            prices=prices_by_item.get(item_id, ()),
        )
        for item_id, (name, quantity) in sorted(items.items())
    )


def _load_item_exchange_prices(
    session: Session,
    item_ids: Iterable[int],
) -> dict[int, tuple[PetItemPriceSnapshot, ...]]:
    ids = tuple(sorted({int(item_id) for item_id in item_ids if item_id > 0}))
    if not ids:
        return {}
    columns = _table_columns(session, ITEM_EXCHANGE_PRICE_TABLE)
    item_name = (
        "COALESCE(NULLIF(item.name, ''), NULLIF(exchange_price.item_name, ''), '')"
        if "item_name" in columns
        else "COALESCE(item.name, '')"
    )
    currency_name = (
        "COALESCE(NULLIF(exchange_price.currency_name, ''), "
        "NULLIF(currency.name, ''), '')"
        if "currency_name" in columns
        else "COALESCE(currency.name, '')"
    )
    statement = text(
        f"""
        SELECT exchange_price.item_id,
               CASE WHEN exchange_price.source_key = :special_key
                    THEN :special_name
                    ELSE exchange_price.source_name
               END AS source_name,
               {item_name} AS item_name,
               exchange_price.item_quantity, exchange_price.currency_item_id,
               {currency_name} AS currency_name, exchange_price.amount,
               exchange_price.purchase_limit
        FROM {ITEM_EXCHANGE_PRICE_TABLE} AS exchange_price
        LEFT JOIN item ON item.id = exchange_price.item_id
        LEFT JOIN item AS currency ON currency.id = exchange_price.currency_item_id
        WHERE exchange_price.item_id IN :item_ids
          AND (exchange_price.start_time <= 0 OR exchange_price.start_time <= :now)
          AND (exchange_price.end_time <= 0 OR :now <= exchange_price.end_time)
        ORDER BY exchange_price.item_id, exchange_price.source_name,
                 exchange_price.amount, exchange_price.source_entry_id
        """
    ).bindparams(bindparam("item_ids", expanding=True))
    try:
        rows = session.execute(
            statement,
            {
                "item_ids": ids,
                "now": int(time.time()),
                "special_key": _SPECIAL_SKILL_SHOP_SOURCE_KEY,
                "special_name": _SPECIAL_SKILL_SHOP_SOURCE_NAME,
            },
        ).mappings()
    except SQLAlchemyError:
        logger.debug("item exchange price data is unavailable", exc_info=True)
        return {}

    result: dict[int, list[PetItemPriceSnapshot]] = {}
    for row in rows:
        item_id = int(row["item_id"])
        prices = result.setdefault(item_id, [])
        if len(prices) >= MAX_ITEM_EXCHANGE_PRICE_ROWS:
            continue
        currency_id = int(row["currency_item_id"])
        currency_name = str(row["currency_name"] or "").strip()
        prices.append(
            PetItemPriceSnapshot(
                source_name=str(row["source_name"] or "兑换"),
                item_name=str(row["item_name"] or "").strip(),
                item_quantity=int(row["item_quantity"] or 1),
                currency_item_id=currency_id,
                currency_name=(
                    currency_name
                    or _LEGACY_CURRENCY_NAMES.get(currency_id, f"道具{currency_id}")
                ),
                amount=int(row["amount"]),
                purchase_limit=(
                    int(row["purchase_limit"])
                    if row["purchase_limit"] is not None
                    else None
                ),
            )
        )
    return {item_id: tuple(prices) for item_id, prices in result.items()}


def _table_columns(session: Session, name: str) -> set[str]:
    try:
        rows = session.execute(text(f"PRAGMA table_info({name})")).mappings()
        return {str(row["name"]) for row in rows}
    except SQLAlchemyError:
        return set()


def _load_partner(session: Session, pet_id: int) -> PetPartnerSnapshot | None:
    statement = text(
        """
        SELECT partner_group.group_id, partner_group.name AS group_name,
               partner_group.cost_item_id,
               COALESCE(NULLIF(cost_item.name, ''), partner_group.cost_item_name)
                   AS cost_item_name,
               partner_group.cost_item_quantity,
               CASE WHEN partner_upgrade.source = :normalized_source
                    THEN COALESCE(partner_upgrade.before_description, '')
                    ELSE COALESCE(partner_upgrade.after_description, '')
               END AS before_description,
               CASE WHEN partner_upgrade.source = :normalized_source
                    THEN COALESCE(partner_upgrade.after_description, '')
                    ELSE COALESCE(partner_upgrade.before_description, '')
               END AS after_description,
               partner_upgrade.skill_id, COALESCE(skill.name, '') AS skill_name,
               activation_item.id AS activation_item_id,
               COALESCE(activation_item.name, '') AS activation_item_name,
               COALESCE(activation_item.item_number, 1) AS activation_item_quantity
        FROM pet_partner_member AS current_member
        JOIN pet_partner_group AS partner_group
          ON partner_group.group_id = current_member.group_id
        LEFT JOIN item AS cost_item ON cost_item.id = partner_group.cost_item_id
        LEFT JOIN pet_partner_upgrade AS partner_upgrade
          ON partner_upgrade.pet_id = current_member.pet_id
        LEFT JOIN skill ON skill.id = partner_upgrade.skill_id
        LEFT JOIN skillinpetorm AS skill_link
          ON skill_link.pet_id = current_member.pet_id
         AND skill_link.skill_id = partner_upgrade.skill_id
        LEFT JOIN skill_activation_item AS activation_item
          ON activation_item.id = skill_link.skill_activation_item_id
        WHERE current_member.pet_id = :pet_id
        ORDER BY partner_group.group_id
        LIMIT 1
        """
    )
    try:
        row = session.execute(
            statement,
            {"pet_id": pet_id, "normalized_source": _NORMALIZED_PARTNER_UPGRADE_SOURCE},
        ).mappings().first()
    except SQLAlchemyError:
        logger.debug("pet partner data is unavailable", exc_info=True)
        return None
    if row is None:
        return None

    requirements = [
        (
            int(row["cost_item_id"]),
            str(row["cost_item_name"] or ""),
            int(row["cost_item_quantity"] or 1),
        )
    ]
    activation_id = int(row["activation_item_id"] or 0)
    activation_name = str(row["activation_item_name"] or "").strip()
    if activation_id > 0 and activation_name:
        requirements.append(
            (
                activation_id,
                activation_name,
                int(row["activation_item_quantity"] or 1),
            )
        )
    prices = _load_item_exchange_prices(
        session,
        (item_id for item_id, _name, _quantity in requirements),
    )

    def item(item_id: int, name: str, quantity: int) -> PetItemSnapshot:
        return PetItemSnapshot(
            id=item_id,
            name=name or f"道具{item_id}",
            quantity=max(1, quantity),
            prices=prices.get(item_id, ()),
        )

    skill_id = int(row["skill_id"] or 0)
    return PetPartnerSnapshot(
        group_id=int(row["group_id"]),
        name=str(row["group_name"] or "").strip(),
        cost_item=item(*requirements[0]),
        before_description=str(row["before_description"] or "").strip(),
        after_description=str(row["after_description"] or "").strip(),
        skill=(
            PetPartnerSkillSnapshot(
                id=skill_id,
                name=str(row["skill_name"] or "").strip() or f"技能{skill_id}",
                activation_item=(
                    item(*requirements[1]) if len(requirements) > 1 else None
                ),
            )
            if skill_id > 0
            else None
        ),
    )


def _load_skill_mintmarks(
    session: Session,
    pet: PetORM,
    skills: Sequence[PetSkillSnapshot],
) -> tuple[PetMintmarkSnapshot, ...]:
    skill_ids = [skill.id for skill in skills]
    if not skill_ids:
        return ()
    statement = (
        select(MintmarkORM)
        .outerjoin(
            SkillMintmarkLink,
            col(SkillMintmarkLink.mintmark_id) == col(MintmarkORM.id),
        )
        .outerjoin(
            PetMintmarkLink,
            col(PetMintmarkLink.mintmark_id) == col(MintmarkORM.id),
        )
        .where(
            col(SkillMintmarkLink.skill_id).in_(skill_ids)
            | (col(PetMintmarkLink.pet_id) == pet.id)
        )
        .where(
            col(PetMintmarkLink.pet_id).is_(None)
            | (col(PetMintmarkLink.pet_id) == pet.id)
        )
        .distinct()
    )
    skill_names = {skill.name for skill in skills if skill.id != _HIDDEN_SKILL_ID}
    return tuple(
        PetMintmarkSnapshot(
            id=int(mintmark.id),
            name=str(mintmark.name),
            description=str(mintmark.desc or ""),
            skill_names=tuple(
                dict.fromkeys(
                    str(skill.name)
                    for skill in mintmark.skill
                    if str(skill.name) in skill_names
                )
            ),
        )
        for mintmark in session.execute(statement).scalars().all()
    )
