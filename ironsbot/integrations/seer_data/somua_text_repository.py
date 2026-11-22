# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve Somua text from one leased publication, never from temporary exports."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.somua_presentation import SomuaEntryText, SomuaTextSnapshot

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlmodel import Session

    from ironsbot.services.seer.data import SeerDataReader
    from ironsbot.services.seer.somua_models import SomuaDetail

logger = logging.getLogger(__name__)


class PublishedSomuaTextResolver:
    def __init__(self, data: SeerDataReader) -> None:
        self._data = data

    def resolve(self, detail: SomuaDetail) -> SomuaTextSnapshot:
        try:
            with self._data.query(lambda session: _load(session, detail)) as result:
                return result
        except (DataUnavailableError, SQLAlchemyError) as error:
            logger.warning(
                "Somua text publication unavailable: %s", type(error).__name__
            )
            return SomuaTextSnapshot(unavailable=("资料配置",))


def _rows(  # noqa: PLR0913 - fixed publication table projection
    session: Session,
    table: str,
    fields: tuple[str, ...],
    key: str,
    ids: set[int],
    unavailable: list[str],
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    ids = {value for value in ids if value > 0}
    if not ids:
        return ()
    try:
        columns = {
            str(row[1]) for row in session.execute(text(f"PRAGMA table_info({table})"))
        }
        if not set(fields) <= columns:
            unavailable.append(label)
            return ()
        statement = text(
            f"SELECT {', '.join(fields)} FROM {table} WHERE {key} IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        return tuple(
            {field: row[field] for field in fields}
            for row in session.execute(
                statement, {"ids": tuple(sorted(ids))}
            ).mappings()
        )
    except SQLAlchemyError as error:
        logger.warning(
            "Somua text table unavailable: table=%s error=%s",
            table,
            type(error).__name__,
        )
        unavailable.append(label)
        return ()


def _load(session: Session, detail: SomuaDetail) -> SomuaTextSnapshot:
    unavailable: list[str] = []
    entries = _rows(
        session,
        "somua_entry",
        ("id", "name", "desc", "type"),
        "id",
        {detail.personality, detail.attack_mode, *detail.attributes},
        unavailable,
        "性格／魂印／能力词条",
    )
    genes = _rows(
        session,
        "somua_gene",
        ("id", "gene"),
        "id",
        set(detail.genes),
        unavailable,
        "基因",
    )
    part_ids = {
        value
        for parts in (detail.parts, detail.father.parts, detail.mother.parts)
        for value in asdict(parts).values()
    }
    parts = _rows(
        session,
        "somua_model",
        ("pet_id", "name"),
        "pet_id",
        part_ids,
        unavailable,
        "外观部件",
    )
    names: dict[int, set[str]] = {}
    for row in parts:
        if (
            isinstance(row["pet_id"], int)
            and isinstance(row["name"], str)
            and row["name"].strip()
        ):
            names.setdefault(row["pet_id"], set()).add(row["name"].strip())
    return SomuaTextSnapshot(
        entries={
            row["id"]: SomuaEntryText(row["name"], row["desc"], row["type"])
            for row in entries
            if isinstance(row["id"], int)
            and isinstance(row["type"], int)
            and isinstance(row["name"], str)
            and isinstance(row["desc"], str)
        },
        genes={
            row["id"]: row["gene"]
            for row in genes
            if isinstance(row["id"], int) and isinstance(row["gene"], str)
        },
        parts={
            key: next(iter(values)) for key, values in names.items() if len(values) == 1
        },
        unavailable=tuple(unavailable),
    )
