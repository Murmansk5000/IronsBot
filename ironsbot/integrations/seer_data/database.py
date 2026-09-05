# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, TypeVar, cast

from seerapi_models import ApiMetadataORM, ErrorCodeORM, MintmarkORM, PeakSeasonORM
from seerapi_models.mintmark import AbilityPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.orm import selectinload
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
    from sqlmodel import Session as SQLModelSession

    from ironsbot.integrations.db_registry import DatabaseManager

UNKNOWN_VERSION = "unknown"
_RENDER_MANIFEST_CONTRACT_VERSION = "2"
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
        self._published_version = UNKNOWN_VERSION
        self._published_render_scopes: frozenset[str] = frozenset()
        self._published_render_assets: PublishedRenderAssetSnapshot | None = None
        self.mintmark = build_mintmark_data_getter(
            merge_connected=merge_connected_mintmarks
        )
        databases.add_load_validator(SEERAPI_DB, validate_published_seerapi_release)
        databases.add_load_listener(SEERAPI_DB, self._refresh_published_version)
        self._refresh_published_version()

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
        """Return the release version cached when the in-memory DB was loaded."""

        return self._published_version

    def render_category_available(self, category: str) -> bool:
        """Return whether the loaded release proves all assets for a renderer."""

        scope = {
            "pet_info": "pet_info",
            "type_matchup": "type_matchup",
            "peak_pool": "peak_pool",
            "peak_pool_vote": "peak_pool",
            "peak_pet_rank": "peak_pool",
            "new_content": "new_content_standard",
            "player_lineup": "pet_info",
        }.get(category)
        return scope is not None and scope in self._published_render_scopes

    def render_asset_snapshot(self) -> PublishedRenderAssetSnapshot | None:
        """Return the immutable image source for the currently loaded release."""

        return self._published_render_assets

    def render_asset_cache_identity(self) -> str:
        snapshot = self._published_render_assets
        return "unknown" if snapshot is None else snapshot.cache_identity

    def _refresh_published_version(self) -> None:
        """Refresh only after an atomic database load, never per cache lookup."""
        try:
            with self._databases.session(SEERAPI_DB) as session:
                if session is None:
                    self._published_version = UNKNOWN_VERSION
                    self._published_render_scopes = frozenset()
                    self._published_render_assets = None
                    return
                metadata = session.exec(select(ApiMetadataORM)).first()
                if metadata is not None:
                    manifest_metadata: dict[str, str] = {}
                    try:
                        metadata_rows = session.execute(
                            text(
                                "SELECT key, value FROM ironsbot_metadata WHERE key IN "
                                "(:revision, :contract, :scopes, :repository, "
                                ":asset_revision)"
                            ),
                            {
                                "revision": "render_asset_manifest_revision",
                                "contract": "render_asset_manifest_contract_version",
                                "scopes": "render_asset_manifest_complete_scopes",
                                "repository": (
                                    "render_asset_manifest_asset_repository"
                                ),
                                "asset_revision": (
                                    "render_asset_manifest_asset_repository_revision"
                                ),
                            },
                        ).all()
                        manifest_metadata = {
                            str(key): str(value) for key, value in metadata_rows
                        }
                        manifest_revision = manifest_metadata.get(
                            "render_asset_manifest_revision"
                        )
                        raw_scopes = json.loads(
                            manifest_metadata.get(
                                "render_asset_manifest_complete_scopes", "[]"
                            )
                        )
                        if isinstance(raw_scopes, list) and all(
                            isinstance(scope, str) and scope for scope in raw_scopes
                        ):
                            snapshot = parse_published_render_asset_snapshot(
                                manifest_metadata,
                                contract_version=_RENDER_MANIFEST_CONTRACT_VERSION,
                            )
                            scopes = frozenset(raw_scopes)
                        else:
                            snapshot = None
                            scopes = frozenset()
                    except Exception:  # noqa: BLE001
                        manifest_revision = None
                        snapshot = None
                        scopes = frozenset()
                    if (
                        not manifest_revision
                        or snapshot is None
                    ):
                        self._published_version = UNKNOWN_VERSION
                        self._published_render_scopes = frozenset()
                        self._published_render_assets = None
                        return
                    self._published_render_scopes = scopes
                    self._published_render_assets = PublishedRenderAssetSnapshot(
                        repository=snapshot.repository,
                        revision=snapshot.revision,
                        manifest_revision=snapshot.manifest_revision,
                        scopes=scopes,
                    )
                    self._published_version = ":".join(
                        (
                            metadata.generate_time.isoformat(),
                            str(manifest_revision),
                        )
                    )
                    return
        except Exception:  # noqa: BLE001
            logger.debug("failed to query Seer database version", exc_info=True)
        self._published_version = UNKNOWN_VERSION
        self._published_render_scopes = frozenset()
        self._published_render_assets = None


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
