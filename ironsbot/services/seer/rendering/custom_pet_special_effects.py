# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.ai.analysis_parser import AnalyzeDescParser

from .custom_pet_models import SpecialEffectDict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from seerapi_models import PetORM


EFFECT_DESCRIPTION_TABLE = "effect_description"
SPECIAL_EFFECT_STATUS_TABLE = "special_effect_status"
GLOSSARY_ENTRY_TABLE = "glossary_entry"
GLOSSARY_LINK_TABLE = "glossaryentrylink"
GLOSSARY_SOURCE = "\u5b98\u65b9\u5173\u8054\u8bcd\u6761"
STATUS_SOURCE = "\u5b98\u65b9\u72b6\u6001\u5173\u8054"
STATUS_NAME_SOURCE = "\u5b98\u65b9\u540c\u540d\u72b6\u6001"
SOULMARK_STATUS_SOURCE_PREFIX = "\u9b42\u5370\u72b6\u6001"
SOULMARK_EFFECT_SOURCE_PREFIX = "\u9b42\u5370\u8bcd\u6761"
SKILL_SOURCE_PREFIX = "\u6280\u80fd\u00b7"
HIDDEN_SKILL_ID = 19002
_SPECIAL_EFFECT_COLOR = "#f35555"
_STATUS_HIGHLIGHT_COLORS = ("#f35555", "#57c975")
_RED_EFFECT_SEPARATORS = re.compile(r"[\s\u3001\uff0c,\uff1b;]+")
_GLOSSARY_ID_SUFFIX = re.compile(r"\(\d+\)$")
_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_STATUS_CONTEXT_MIN_SCORE = 0.25
_STATUS_CONTEXT_MIN_DELTA = 0.03
logger = logging.getLogger(__name__)


def _normalize_effect_text(value: str | None) -> str:
    return re.sub(r"[\W_]+", "", value or "").casefold()


def _numeric_overlap_score(candidate: str, context: str) -> float:
    numbers = set(_NUMBER_PATTERN.findall(candidate))
    if not numbers:
        return 0.0
    context_numbers = set(_NUMBER_PATTERN.findall(context))
    return sum(1.0 for number in numbers if number in context_numbers) / len(numbers)


def _status_match_score(description: str | None, context: str) -> float:
    candidate = _normalize_effect_text(description)
    normalized_context = _normalize_effect_text(context)
    if not candidate or not normalized_context:
        return 0.0
    if candidate in normalized_context:
        return 2.0
    return SequenceMatcher(None, candidate, normalized_context).ratio() + (
        _numeric_overlap_score(candidate, normalized_context) * 0.5
    )


def _clean_highlighted_term(value: str) -> str:
    return _GLOSSARY_ID_SUFFIX.sub("", value.strip())


def _highlighted_terms(value: str | None, colors: Iterable[str]) -> list[str]:
    parser = AnalyzeDescParser(value or "")
    terms: list[str] = []
    for color in colors:
        for term in parser.colored_texts(color):
            clean = _clean_highlighted_term(term)
            if clean and clean not in terms:
                terms.append(clean)
    return terms


def _assign_special_effect_colors(
    pet: PetORM,
    effects: list[SpecialEffectDict],
) -> None:
    """Use the first official highlight for an effect, with a stable fallback."""
    colors_by_name: dict[str, str] = {}
    names = {effect["name"] for effect in effects}
    if names:
        descriptions = [
            description for description, _source in _skill_effect_texts(pet)
        ]
        descriptions.extend(
            str(soulmark.analyze_desc or "") for soulmark in pet.soulmark
        )
        for description in descriptions:
            for segment in AnalyzeDescParser(description).segments:
                if not segment.colors:
                    continue
                for name in names:
                    if name in segment.text and name not in colors_by_name:
                        colors_by_name[name] = segment.colors[-1]

    for effect in effects:
        effect["color"] = colors_by_name.get(effect["name"], _SPECIAL_EFFECT_COLOR)


def _extract_special_effects(pet: PetORM) -> list[SpecialEffectDict]:
    """Return only official glossary entries directly linked to this pet."""
    effects_by_name: dict[str, SpecialEffectDict] = {}
    for glossary in pet.glossary_entry:
        name = str(glossary.name or "").strip()
        if not name:
            continue
        description = str(glossary.desc or "").strip() or None
        effects_by_name.setdefault(
            name,
            SpecialEffectDict(
                name=name,
                desc=description,
                sources=[GLOSSARY_SOURCE],
                glossary_id=(
                    int(glossary.id)
                    if getattr(glossary, "id", None) is not None
                    else None
                ),
                status_id=None,
                icon=None,
            ),
        )
    return list(effects_by_name.values())


def _split_official_effect_names(
    value: str,
    official_names: frozenset[str],
) -> list[str]:
    """Split a red span only when official names cover the entire span."""
    compact = _RED_EFFECT_SEPARATORS.sub("", value.strip())
    if not compact:
        return []

    names = tuple(
        sorted(
            (name for name in official_names if name and name in compact),
            key=len,
            reverse=True,
        )
    )
    matches: list[list[str] | None] = [None] * (len(compact) + 1)
    matches[0] = []
    for start in range(len(compact)):
        prefix = matches[start]
        if prefix is None:
            continue
        for name in names:
            if compact.startswith(name, start):
                end = start + len(name)
                if matches[end] is None:
                    matches[end] = [*prefix, name]
    return list(dict.fromkeys(matches[-1] or []))


def _skill_effect_texts(pet: PetORM) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for skill_link in pet.skill_links:
        skill = skill_link.skill
        if int(skill.id) == HIDDEN_SKILL_ID:
            continue
        source = f"{SKILL_SOURCE_PREFIX}{skill.name}"
        if skill.info:
            texts.append((str(skill.info), source))
        for effect in (*skill.skill_effect, *skill.friend_skill_effect):
            description = effect.analyze_info or effect.info
            if description:
                texts.append((str(description), source))
        if skill.hide_effect and skill.hide_effect.description:
            texts.append((str(skill.hide_effect.description), source))
    return texts


def _add_skill_red_effects(
    session: Any,
    pet: PetORM,
    effects: list[SpecialEffectDict],
) -> None:
    """Add exact official EffectDes terms highlighted red in this pet's skills."""
    _ensure_effect_ids(effects)
    try:
        rows = session.execute(
            text(
                f"""
                SELECT name, description
                FROM {EFFECT_DESCRIPTION_TABLE}
                WHERE name <> '' AND description <> ''
                ORDER BY effect_id
                """
            )
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official effect description data is unavailable "
            "in the current SQLite release",
            exc_info=True,
        )
        return

    descriptions = {
        str(raw_name).strip(): str(raw_description).strip()
        for raw_name, raw_description in rows
        if str(raw_name or "").strip() and str(raw_description or "").strip()
    }
    official_names = frozenset(descriptions)
    effects_by_name = {effect["name"]: effect for effect in effects}
    for description, source in _skill_effect_texts(pet):
        for red_text in AnalyzeDescParser(description).colored_texts(
            _SPECIAL_EFFECT_COLOR
        ):
            for name in _split_official_effect_names(red_text, official_names):
                effect = effects_by_name.get(name)
                if effect is None:
                    effect = SpecialEffectDict(
                        name=name,
                        desc=descriptions[name],
                        sources=[source],
                        glossary_id=None,
                        status_id=None,
                        icon=None,
                    )
                    effects_by_name[name] = effect
                    effects.append(effect)
                    continue
                if effect["desc"] is None:
                    effect["desc"] = descriptions[name]
                if source not in effect["sources"]:
                    effect["sources"].append(source)


def _fetch_status_rows_by_names(
    session: Any,
    names: Iterable[str],
) -> dict[str, list[tuple[int, str, str | None]]]:
    clean_names = tuple(dict.fromkeys(name for name in names if name))
    if not clean_names:
        return {}

    placeholders = ", ".join(f":name_{index}" for index, _ in enumerate(clean_names))
    params = {f"name_{index}": name for index, name in enumerate(clean_names)}
    try:
        rows = session.execute(
            text(
                f"""
                SELECT status_id, name, description
                FROM {SPECIAL_EFFECT_STATUS_TABLE}
                WHERE name IN ({placeholders})
                ORDER BY status_id
                """
            ),
            params,
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official special effect status data is unavailable "
            "in the current SQLite release",
            exc_info=True,
        )
        return {}

    by_name: dict[str, list[tuple[int, str, str | None]]] = {}
    for raw_status_id, raw_name, raw_description in rows:
        name = str(raw_name or "").strip()
        if not name:
            continue
        description = str(raw_description or "").strip() or None
        by_name.setdefault(name, []).append((int(raw_status_id), name, description))
    return by_name


def _fetch_effect_descriptions_by_names(
    session: Any,
    names: Iterable[str],
) -> dict[str, str]:
    clean_names = tuple(dict.fromkeys(name for name in names if name))
    if not clean_names:
        return {}

    placeholders = ", ".join(f":name_{index}" for index, _ in enumerate(clean_names))
    params = {f"name_{index}": name for index, name in enumerate(clean_names)}
    try:
        rows = session.execute(
            text(
                f"""
                SELECT name, description
                FROM {EFFECT_DESCRIPTION_TABLE}
                WHERE name IN ({placeholders})
                    AND description <> ''
                ORDER BY effect_id
                """
            ),
            params,
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official effect description data is unavailable "
            "in the current SQLite release",
            exc_info=True,
        )
        return {}

    return {
        str(raw_name).strip(): str(raw_description).strip()
        for raw_name, raw_description in rows
        if str(raw_name or "").strip() and str(raw_description or "").strip()
    }


def _choose_status_for_context(
    rows: list[tuple[int, str, str | None]],
    context: str,
) -> tuple[int, str, str | None] | None:
    if len(rows) == 1:
        return rows[0]
    normalized_descriptions = [
        _normalize_effect_text(description) for _status_id, _name, description in rows
    ]
    if all(normalized_descriptions) and len(set(normalized_descriptions)) == 1:
        return min(rows, key=lambda row: row[0])
    ranked = sorted(
        (
            (_status_match_score(description, context), status_id, name, description)
            for status_id, name, description in rows
        ),
        reverse=True,
    )
    if not ranked:
        return None
    best_score, status_id, name, description = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if (
        best_score >= _STATUS_CONTEXT_MIN_SCORE
        and best_score > second_score + _STATUS_CONTEXT_MIN_DELTA
    ):
        return status_id, name, description
    return None


def _upsert_status_effect(
    effects: list[SpecialEffectDict],
    *,
    status_id: int,
    name: str,
    description: str | None,
    source: str,
) -> None:
    for effect in effects:
        if effect["name"] != name:
            continue
        if effect["status_id"] in (None, status_id):
            if effect["desc"] is None and description is not None:
                effect["desc"] = description
            if source not in effect["sources"]:
                effect["sources"].append(source)
            if effect["status_id"] is None:
                effect["status_id"] = status_id
            return

    effects.append(
        SpecialEffectDict(
            name=name,
            desc=description,
            sources=[source],
            glossary_id=None,
            status_id=status_id,
            icon=None,
        )
    )


def _upsert_effect_description(
    effects: list[SpecialEffectDict],
    *,
    name: str,
    description: str,
    source: str,
) -> None:
    for effect in effects:
        if effect["name"] != name:
            continue
        if effect["desc"] is None:
            effect["desc"] = description
        if source not in effect["sources"]:
            effect["sources"].append(source)
        return

    effects.append(
        SpecialEffectDict(
            name=name,
            desc=description,
            sources=[source],
            glossary_id=None,
            status_id=None,
            icon=None,
        )
    )


def _add_named_status_icons(
    session: Any,
    effects: list[SpecialEffectDict],
) -> None:
    """Attach a sign-buff icon when an already trusted effect name is unique."""
    _ensure_effect_ids(effects)
    by_name = _fetch_status_rows_by_names(
        session,
        (effect["name"] for effect in effects),
    )
    for effect in effects:
        if effect["status_id"] is not None:
            continue
        rows = by_name.get(effect["name"], [])
        if len(rows) != 1:
            continue
        status_id, _name, description = rows[0]
        if effect["desc"] is None and description is not None:
            effect["desc"] = description
        if STATUS_NAME_SOURCE not in effect["sources"]:
            effect["sources"].append(STATUS_NAME_SOURCE)
        effect["status_id"] = status_id


def _collect_soulmark_highlight_terms(
    pet: PetORM,
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[int]]]:
    soulmark_terms: dict[str, list[tuple[int, str]]] = {}
    red_soulmark_terms: dict[str, list[int]] = {}
    for soulmark in pet.soulmark:
        context = "\n".join(
            part
            for part in (
                str(soulmark.desc or ""),
                str(soulmark.analyze_desc or ""),
                str(getattr(soulmark, "desc_formatting_adjustment", "") or ""),
            )
            if part
        )
        for term in _highlighted_terms(soulmark.analyze_desc, _STATUS_HIGHLIGHT_COLORS):
            soulmark_terms.setdefault(term, []).append((int(soulmark.id), context))
        for term in _highlighted_terms(
            soulmark.analyze_desc,
            (_SPECIAL_EFFECT_COLOR,),
        ):
            red_soulmark_terms.setdefault(term, []).append(int(soulmark.id))
    return soulmark_terms, red_soulmark_terms


def _add_soulmark_status_effects(
    session: Any,
    effects: list[SpecialEffectDict],
    soulmark_terms: dict[str, list[tuple[int, str]]],
) -> set[str]:
    by_name = _fetch_status_rows_by_names(session, soulmark_terms)
    resolved_status_terms: set[str] = set()
    for term, contexts in soulmark_terms.items():
        rows = by_name.get(term, [])
        if not rows:
            continue
        for soulmark_id, context in contexts:
            status = _choose_status_for_context(rows, context)
            if status is None:
                continue
            status_id, name, description = status
            _upsert_status_effect(
                effects,
                status_id=status_id,
                name=name,
                description=description,
                source=f"{SOULMARK_STATUS_SOURCE_PREFIX}{soulmark_id}",
            )
            resolved_status_terms.add(term)
    return resolved_status_terms


def _add_soulmark_highlight_effects(
    session: Any,
    pet: PetORM,
    effects: list[SpecialEffectDict],
) -> None:
    """Resolve official soulmark highlights to statuses or named effect entries."""
    _ensure_effect_ids(effects)
    soulmark_terms, red_soulmark_terms = _collect_soulmark_highlight_terms(pet)
    resolved_status_terms = _add_soulmark_status_effects(
        session,
        effects,
        soulmark_terms,
    )
    effect_descriptions = _fetch_effect_descriptions_by_names(
        session,
        red_soulmark_terms,
    )
    for term, soulmark_ids in red_soulmark_terms.items():
        if term in resolved_status_terms:
            continue
        description = effect_descriptions.get(term)
        if description is None:
            continue
        for soulmark_id in soulmark_ids:
            _upsert_effect_description(
                effects,
                name=term,
                description=description,
                source=f"{SOULMARK_EFFECT_SOURCE_PREFIX}{soulmark_id}",
            )


def _add_pet_linked_status_effects(
    session: Any,
    effects: list[SpecialEffectDict],
    *,
    pet_id: int,
) -> None:
    """Add statuses whose official record explicitly identifies this pet."""
    _ensure_effect_ids(effects)
    try:
        rows = session.execute(
            text(
                f"""
                SELECT status_id, name, description
                FROM {SPECIAL_EFFECT_STATUS_TABLE}
                WHERE show_monster_id = :pet_id
                ORDER BY status_id
                """
            ),
            {"pet_id": pet_id},
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official special effect status data is unavailable "
            "in the current SQLite release",
            exc_info=True,
        )
        return

    effects_by_name = {effect["name"]: effect for effect in effects}
    for status_id, raw_name, raw_description in rows:
        name = str(raw_name or "").strip()
        if not name:
            continue
        description = str(raw_description or "").strip() or None
        effect = effects_by_name.get(name)
        if effect is None:
            effect = SpecialEffectDict(
                name=name,
                desc=description,
                sources=[STATUS_SOURCE],
                glossary_id=None,
                status_id=int(status_id),
                icon=None,
            )
            effects_by_name[name] = effect
            effects.append(effect)
            continue

        if effect["desc"] is None and description is not None:
            effect["desc"] = description
        if STATUS_SOURCE not in effect["sources"]:
            effect["sources"].append(STATUS_SOURCE)
        if effect["status_id"] is None:
            effect["status_id"] = int(status_id)


def _ensure_effect_ids(effects: list[SpecialEffectDict]) -> None:
    """Provide metadata defaults for effects created by older helper callers."""
    for effect in effects:
        effect.setdefault("glossary_id", None)
        effect.setdefault("status_id", None)


def _resolve_glossary_ids(
    session: Any,
    effects: list[SpecialEffectDict],
) -> None:
    """Resolve status-derived effects to an official glossary entry when unambiguous."""
    _ensure_effect_ids(effects)
    names = tuple(
        dict.fromkeys(
            effect["name"] for effect in effects if effect["glossary_id"] is None
        )
    )
    if not names:
        return

    placeholders = ", ".join(f":name_{index}" for index, _ in enumerate(names))
    params = {f"name_{index}": name for index, name in enumerate(names)}
    try:
        rows = session.execute(
            text(
                f"""
                SELECT id, name, desc
                FROM {GLOSSARY_ENTRY_TABLE}
                WHERE name IN ({placeholders})
                ORDER BY id
                """
            ),
            params,
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official glossary data is unavailable in the current SQLite release",
            exc_info=True,
        )
        return

    candidates: dict[str, list[tuple[int, str | None]]] = {}
    for raw_id, raw_name, raw_description in rows:
        name = str(raw_name or "").strip()
        if name:
            candidates.setdefault(name, []).append(
                (int(raw_id), str(raw_description or "").strip() or None)
            )

    for effect in effects:
        if effect["glossary_id"] is not None:
            continue
        matching = candidates.get(effect["name"], [])
        if len(matching) == 1:
            effect["glossary_id"] = matching[0][0]
            continue
        normalized_description = _normalize_effect_text(effect["desc"])
        exact = [
            glossary_id
            for glossary_id, description in matching
            if normalized_description
            and _normalize_effect_text(description) == normalized_description
        ]
        if len(exact) == 1:
            effect["glossary_id"] = exact[0]


def _add_linked_glossary_effects(
    session: Any,
    effects: list[SpecialEffectDict],
) -> None:
    """Add one official glossary-link layer without inferring from prose."""
    _resolve_glossary_ids(session, effects)
    source_ids = tuple(
        dict.fromkeys(
            effect["glossary_id"]
            for effect in effects
            if effect["glossary_id"] is not None
        )
    )
    if not source_ids:
        return

    placeholders = ", ".join(
        f":source_id_{index}" for index, _ in enumerate(source_ids)
    )
    params = {
        f"source_id_{index}": source_id for index, source_id in enumerate(source_ids)
    }
    try:
        rows = session.execute(
            text(
                f"""
                SELECT link.source_id, target.id, target.name, target.desc
                FROM {GLOSSARY_LINK_TABLE} AS link
                JOIN {GLOSSARY_ENTRY_TABLE} AS target ON target.id = link.target_id
                WHERE link.source_id IN ({placeholders})
                  AND link.source_id <> link.target_id
                ORDER BY link.source_id, target.id
                """
            ),
            params,
        ).all()
    except SQLAlchemyError:
        logger.debug(
            "official glossary links are unavailable in the current SQLite release",
            exc_info=True,
        )
        return

    existing_by_id = {
        effect["glossary_id"]: effect
        for effect in effects
        if effect["glossary_id"] is not None
    }
    for _source_id, raw_target_id, raw_name, raw_description in rows:
        target_id = int(raw_target_id)
        if target_id in existing_by_id:
            continue
        name = str(raw_name or "").strip()
        if not name:
            continue
        description = str(raw_description or "").strip() or None
        matching_effect = next(
            (
                effect
                for effect in effects
                if effect["glossary_id"] is None
                and effect["name"] == name
                and _normalize_effect_text(effect["desc"])
                == _normalize_effect_text(description)
            ),
            None,
        )
        if matching_effect is None:
            matching_effect = SpecialEffectDict(
                name=name,
                desc=description,
                sources=[GLOSSARY_SOURCE],
                glossary_id=target_id,
                status_id=None,
                icon=None,
            )
            effects.append(matching_effect)
        else:
            matching_effect["glossary_id"] = target_id
            if GLOSSARY_SOURCE not in matching_effect["sources"]:
                matching_effect["sources"].append(GLOSSARY_SOURCE)
        existing_by_id[target_id] = matching_effect


def _sort_special_effects(effects: list[SpecialEffectDict]) -> None:
    """Sort every effect by glossary ID, then status ID, preserving discovery order."""
    _ensure_effect_ids(effects)
    discovered = {id(effect): index for index, effect in enumerate(effects)}

    def sort_key(effect: SpecialEffectDict) -> tuple[int, int, int]:
        sort_id = effect["glossary_id"]
        if sort_id is None:
            sort_id = effect["status_id"]
        if sort_id is None:
            return (1, 0, discovered[id(effect)])
        return (0, int(sort_id), discovered[id(effect)])

    effects.sort(key=sort_key)


def _deduplicate_special_effects(effects: list[SpecialEffectDict]) -> None:
    """Merge entries that identify the same official glossary or status effect."""
    _ensure_effect_ids(effects)
    by_glossary_id: dict[int, SpecialEffectDict] = {}
    by_status_id: dict[int, SpecialEffectDict] = {}
    unique: list[SpecialEffectDict] = []

    for effect in effects:
        glossary_id = effect["glossary_id"]
        status_id = effect["status_id"]
        existing = (
            by_glossary_id.get(glossary_id)
            if glossary_id is not None
            else by_status_id.get(status_id)
            if status_id is not None
            else None
        )
        if existing is None:
            unique.append(effect)
            if glossary_id is not None:
                by_glossary_id[glossary_id] = effect
            elif status_id is not None:
                by_status_id[status_id] = effect
            continue

        if existing["desc"] is None and effect["desc"] is not None:
            existing["desc"] = effect["desc"]
        for source in effect["sources"]:
            if source not in existing["sources"]:
                existing["sources"].append(source)
        if existing["status_id"] is None:
            existing["status_id"] = status_id
        if existing["icon"] is None and effect["icon"] is not None:
            existing["icon"] = effect["icon"]

    effects[:] = unique
