# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypeVar

from seerapi_models import ApiMetadataORM, ErrorCodeORM, PeakSeasonORM
from sqlmodel import select

from ironsbot.services.seer.data import (
    SEERAPI_DB,
    DataGetter,
    DataQuery,
    DataResolver,
    DataUnavailableError,
)

from .getters import (
    BattleEffectDataGetter,
    EquipDataGetter,
    GemCategoryDataGetter,
    MintmarkClassDataGetter,
    PetDataGetter,
    PetSkinDataGetter,
    SuitDataGetter,
    TitleDataGetter,
    TypeCombinationDataGetter,
    build_mintmark_data_getter,
)
from .mintmark_series_resolvers import resolve_custom_mintmark_series

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from seerapi_models import (
        MintmarkClassCategoryORM,
        MintmarkORM,
        PetORM,
        PetSkinORM,
    )

    from ironsbot.integrations.db_registry import DatabaseManager

UNKNOWN_VERSION = "unknown"
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class SeerDatabase:
    battle_effect = BattleEffectDataGetter
    equip = EquipDataGetter
    gem_category = GemCategoryDataGetter
    mintmark_class = MintmarkClassDataGetter
    custom_mintmark_series = staticmethod(resolve_custom_mintmark_series)
    pet = PetDataGetter
    pet_skin = PetSkinDataGetter
    suit = SuitDataGetter
    title = TitleDataGetter
    type_combination = TypeCombinationDataGetter

    def __init__(
        self,
        databases: DatabaseManager,
        *,
        merge_connected_mintmarks: bool,
    ) -> None:
        self._databases = databases
        self.mintmark = build_mintmark_data_getter(
            merge_connected=merge_connected_mintmarks
        )

    @contextmanager
    def query(self, operation: DataQuery[_T]) -> Iterator[_T]:
        with self._databases.session(SEERAPI_DB) as session:
            if session is None:
                raise DataUnavailableError
            yield operation(session)

    @contextmanager
    def resolve(
        self,
        getter: DataResolver[_T],
        arg: str,
    ) -> Iterator[tuple[_T, ...]]:
        with self._databases.all_sessions() as sessions:
            if SEERAPI_DB not in sessions:
                raise DataUnavailableError
            yield getter(sessions, arg)

    @contextmanager
    def get(
        self,
        getter: DataGetter[_T],
        id_: int,
    ) -> Iterator[_T | None]:
        with self.query(lambda session: getter.get(session, id_)) as item:
            yield item

    @contextmanager
    def get_many(
        self,
        getter: DataGetter[_T],
        ids: set[int],
    ) -> Iterator[dict[int, _T]]:
        with self.query(
            lambda session: {
                id_: item
                for id_ in ids
                if (item := getter.get(session, id_)) is not None
            }
        ) as items:
            yield items

    @contextmanager
    def pet_and_skins(
        self,
        arg: str,
    ) -> Iterator[tuple[tuple[PetORM, ...], tuple[PetSkinORM, ...]]]:
        with self._databases.all_sessions() as sessions:
            if SEERAPI_DB not in sessions:
                raise DataUnavailableError
            yield self.pet(sessions, arg), self.pet_skin(sessions, arg)

    @contextmanager
    def mintmark_query(
        self,
        arg: str,
    ) -> Iterator[
        tuple[
            tuple[MintmarkORM, ...],
            tuple[MintmarkClassCategoryORM, ...],
            tuple[MintmarkORM, ...],
        ]
    ]:
        with self._databases.all_sessions() as sessions:
            if SEERAPI_DB not in sessions:
                raise DataUnavailableError
            yield (
                self.mintmark(sessions, arg),
                self.mintmark_class(sessions, arg),
                self.custom_mintmark_series(sessions, arg),
            )

    def error_message(self, result_code: int) -> str | None:
        try:
            with self._databases.session(SEERAPI_DB) as session:
                if session is None:
                    return None
                error = session.get(ErrorCodeORM, result_code)
                return None if error is None else error.message
        except Exception:  # noqa: BLE001
            logger.warning("failed to resolve Seer error code", exc_info=True)
            return None

    def peak_season_start(self) -> datetime | None:
        try:
            with self._databases.session(SEERAPI_DB) as session:
                if session is None:
                    return None
                season = session.get(PeakSeasonORM, 1)
                return None if season is None else season.start_time
        except Exception:  # noqa: BLE001
            return None

    def version(self) -> str:
        try:
            with self._databases.session(SEERAPI_DB) as session:
                if session is None:
                    return UNKNOWN_VERSION
                metadata = session.exec(select(ApiMetadataORM)).first()
                if metadata is not None:
                    return metadata.generate_time.isoformat()
        except Exception:  # noqa: BLE001
            logger.debug("failed to query Seer database version", exc_info=True)
        return UNKNOWN_VERSION
