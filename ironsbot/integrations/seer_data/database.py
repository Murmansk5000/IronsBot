# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar, cast

from seerapi_models import ApiMetadataORM, ErrorCodeORM, MintmarkORM, PeakSeasonORM
from seerapi_models.mintmark import AbilityPartORM, UniversalPartORM
from sqlalchemy.orm import selectinload
from sqlmodel import col, or_, select

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
    from collections.abc import Iterable, Iterator
    from datetime import datetime

    from seerapi_models import PetORM, PetSkinORM
    from sqlmodel import Session as SQLModelSession

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
    ) -> Iterator[tuple[MintmarkORM, ...]]:
        with self._databases.all_sessions() as sessions:
            session = sessions.get(SEERAPI_DB)
            if session is None:
                raise DataUnavailableError
            custom_series = self.custom_mintmark_series(sessions, arg)
            if custom_series:
                mintmark_ids = tuple(mintmark.id for mintmark in custom_series)
            else:
                direct = self.mintmark(sessions, arg)
                classes = self.mintmark_class(sessions, arg)
                class_ids = {mintmark_class.id for mintmark_class in classes}
                class_member_ids = _mintmark_class_member_ids(
                    session,
                    class_ids,
                )
                mintmark_ids = (*(
                    mintmark.id for mintmark in direct
                ), *class_member_ids)
            yield _load_mintmark_details(session, mintmark_ids)

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


def _mintmark_class_member_ids(
    session: SQLModelSession,
    class_ids: set[int],
) -> tuple[int, ...]:
    if not class_ids:
        return ()
    statement = select(UniversalPartORM.mintmark_id).where(
        col(UniversalPartORM.mintmark_class_id).in_(class_ids)
    ).order_by(col(UniversalPartORM.mintmark_id))
    return tuple(session.exec(statement).all())


def _load_mintmark_details(
    session: SQLModelSession,
    mintmark_ids: Iterable[int],
) -> tuple[MintmarkORM, ...]:
    requested_ids = tuple(
        dict.fromkeys(int(mintmark_id) for mintmark_id in mintmark_ids)
    )
    if not requested_ids:
        return ()

    connected_ids = _collect_connected_mintmark_ids(session, requested_ids)
    statement = select(MintmarkORM).where(
        col(MintmarkORM.id).in_(connected_ids)
    ).options(
        selectinload(cast("Any", MintmarkORM.ability_part)).selectinload(
            cast("Any", AbilityPartORM.max_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.skill_part)),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.base_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.max_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.extra_attr_value)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.mintmark_class)
        ),
        selectinload(cast("Any", MintmarkORM.universal_part)).selectinload(
            cast("Any", UniversalPartORM.connect)
        ),
        selectinload(cast("Any", MintmarkORM.connected_universal_parts)).selectinload(
            cast("Any", UniversalPartORM.mintmark)
        ),
        selectinload(cast("Any", MintmarkORM.pet)),
        selectinload(cast("Any", MintmarkORM.skill)),
    )
    loaded = {mintmark.id: mintmark for mintmark in session.exec(statement).all()}
    return tuple(
        mintmark
        for mintmark_id in requested_ids
        if (mintmark := loaded.get(mintmark_id)) is not None
    )


def _collect_connected_mintmark_ids(
    session: SQLModelSession,
    mintmark_ids: Iterable[int],
) -> set[int]:
    result = {int(mintmark_id) for mintmark_id in mintmark_ids}
    pending = set(result)
    while pending:
        related_ids = _connected_mintmark_neighbor_ids(session, pending)
        pending = related_ids - result
        result.update(pending)
    return result


def _connected_mintmark_neighbor_ids(
    session: SQLModelSession,
    mintmark_ids: set[int],
) -> set[int]:
    statement = select(
        UniversalPartORM.mintmark_id,
        UniversalPartORM.connect_id,
    ).where(
        or_(
            col(UniversalPartORM.mintmark_id).in_(mintmark_ids),
            col(UniversalPartORM.connect_id).in_(mintmark_ids),
        )
    )
    related_ids: set[int] = set()
    for mintmark_id, connected_id in session.exec(statement).all():
        if mintmark_id is not None:
            related_ids.add(int(mintmark_id))
        if connected_id is not None:
            related_ids.add(int(connected_id))
    return related_ids
