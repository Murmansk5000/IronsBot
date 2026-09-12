# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Any, TypeVar, cast
from weakref import WeakKeyDictionary

from seerapi_models import ApiMetadataORM, ErrorCodeORM, MintmarkORM, PeakSeasonORM
from seerapi_models.mintmark import AbilityPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.orm import selectinload
from sqlmodel import Session as SQLModelSession
from sqlmodel import col, or_, select

from ironsbot.services.seer.data import (
    SEERAPI_DB,
    DataGetter,
    DataQuery,
    DataResolver,
    DataUnavailableError,
)
from ironsbot.services.seer.images import (
    PublishedRenderAssetSnapshot,
    parse_published_render_asset_snapshot,
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
from .release_contract import validate_published_seerapi_release

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from datetime import datetime

    from seerapi_models import PetORM, PetSkinORM
    from sqlalchemy.engine import Engine

    from ironsbot.integrations.db_registry import DatabaseManager

UNKNOWN_VERSION = "unknown"
_RENDER_MANIFEST_CONTRACT_VERSION = "2"
logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SeerPublication:
    version: str = UNKNOWN_VERSION
    assets: PublishedRenderAssetSnapshot | None = None

    def category_available(self, category: str) -> bool:
        scope = {
            "pet_info": "pet_info",
            "type_matchup": "type_matchup",
            "peak_pool": "peak_pool",
            "peak_pool_vote": "peak_pool",
            "peak_pet_rank": "peak_pool",
            "new_content": "new_content_standard",
            "player_lineup": "peak_pool",
        }.get(category)
        return (
            self.assets is not None
            and scope is not None
            and scope in self.assets.scopes
        )


class SeerSnapshotClosedError(DataUnavailableError):
    def __init__(self) -> None:
        super().__init__("Seer database snapshot is closed")


class SeerReadSnapshot:
    """One leased engine and its publication; SQL sessions stay short-lived."""

    def __init__(self, engine: Engine, publication: SeerPublication) -> None:
        self._engine: Engine | None = engine
        self._publication = publication

    @property
    def publication(self) -> SeerPublication:
        return self._publication

    @contextmanager
    def query(self, operation: DataQuery[_T]) -> Iterator[_T]:
        if self._engine is None:
            raise SeerSnapshotClosedError
        with SQLModelSession(self._engine) as session:
            yield operation(session)

    def close(self) -> None:
        self._engine = None


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
        self._publications: WeakKeyDictionary[Engine, SeerPublication] = (
            WeakKeyDictionary()
        )
        self._publication_lock = RLock()
        self.mintmark = build_mintmark_data_getter(
            merge_connected=merge_connected_mintmarks
        )
        databases.add_load_validator(SEERAPI_DB, self._validate_publication)
        self._publication()

    @contextmanager
    def query(self, operation: DataQuery[_T]) -> Iterator[_T]:
        with self.read_snapshot() as snapshot, snapshot.query(operation) as result:
            yield result

    @contextmanager
    def read_snapshot(self) -> Iterator[SeerReadSnapshot]:
        with self._databases.snapshot((SEERAPI_DB,)) as engines:
            engine = engines.get(SEERAPI_DB)
            if engine is None:
                raise DataUnavailableError
            snapshot = SeerReadSnapshot(engine, self._publication_for(engine))
            try:
                yield snapshot
            finally:
                snapshot.close()

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
        """Return the release version cached when the in-memory DB was loaded."""

        return self._publication().version

    def render_category_available(self, category: str) -> bool:
        """Return whether the loaded release proves all assets for a renderer."""

        return self._publication().category_available(category)

    def render_asset_snapshot(self) -> PublishedRenderAssetSnapshot | None:
        """Return the immutable image source for the currently loaded release."""

        return self._publication().assets

    def _validate_publication(self, engine: Engine) -> None:
        validate_published_seerapi_release(engine)
        self._publication_for(engine)

    def _publication(self) -> SeerPublication:
        with self._databases.snapshot((SEERAPI_DB,)) as engines:
            engine = engines.get(SEERAPI_DB)
            return (
                SeerPublication() if engine is None else self._publication_for(engine)
            )

    def _publication_for(self, engine: Engine) -> SeerPublication:
        with self._publication_lock:
            publication = self._publications.get(engine)
            if publication is None:
                publication = _read_publication(engine)
                self._publications[engine] = publication
            return publication


def _read_publication(engine: Engine) -> SeerPublication:
    """Read once for each engine, before publishing a validated candidate."""
    try:
        with SQLModelSession(engine) as session:
            metadata = session.exec(select(ApiMetadataORM)).first()
            if metadata is None:
                return SeerPublication()
            rows = session.execute(
                text(
                    "SELECT key, value FROM ironsbot_metadata WHERE key IN "
                    "(:revision, :contract, :scopes, :repository, :asset_revision)"
                ),
                {
                    "revision": "render_asset_manifest_revision",
                    "contract": "render_asset_manifest_contract_version",
                    "scopes": "render_asset_manifest_complete_scopes",
                    "repository": "render_asset_manifest_asset_repository",
                    "asset_revision": "render_asset_manifest_asset_repository_revision",
                },
            ).all()
            values = {str(key): str(value) for key, value in rows}
            raw_scopes = json.loads(
                values.get("render_asset_manifest_complete_scopes", "[]")
            )
            if not isinstance(raw_scopes, list) or not all(
                isinstance(scope, str) and scope for scope in raw_scopes
            ):
                return SeerPublication()
            snapshot = parse_published_render_asset_snapshot(
                values, contract_version=_RENDER_MANIFEST_CONTRACT_VERSION
            )
            if snapshot is None:
                return SeerPublication()
            assets = PublishedRenderAssetSnapshot(
                repository=snapshot.repository,
                revision=snapshot.revision,
                manifest_revision=snapshot.manifest_revision,
                scopes=frozenset(raw_scopes),
            )
            return SeerPublication(
                f"{metadata.generate_time.isoformat()}:{snapshot.manifest_revision}",
                assets,
            )
    except Exception:  # noqa: BLE001
        logger.debug("failed to query Seer database version", exc_info=True)
        return SeerPublication()


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
