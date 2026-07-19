# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar

from seerapi_models import ApiMetadataORM
from sqlmodel import Session, select

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from datetime import datetime

    from seerapi_models import (
        BattleEffectORM,
        EquipORM,
        GemCategoryORM,
        MintmarkClassCategoryORM,
        MintmarkORM,
        PetORM,
        PetSkinORM,
        SuitORM,
        TitlePartORM,
        TypeCombinationORM,
    )

SEERAPI_DB = "seerapi"
ALIAS_DB = "aliases"
SessionMap = dict[str, Session]
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)


class DataResolver(Protocol[_T_co]):
    def __call__(self, sessions: SessionMap, arg: str) -> tuple[_T_co, ...]: ...


class DataGetter(DataResolver[_T_co], Protocol[_T_co]):
    def get(self, session: Session, id_: int) -> _T_co | None: ...


class DataQuery(Protocol[_T_co]):
    def __call__(self, session: Session) -> _T_co: ...


class DataUnavailableError(RuntimeError):
    pass


def load_data_generated_at(session: Session) -> datetime | None:
    metadata = session.exec(select(ApiMetadataORM)).first()
    return None if metadata is None else metadata.generate_time


class SeerDataAccess(Protocol):
    @property
    def battle_effect(self) -> DataGetter["BattleEffectORM"]: ...

    @property
    def equip(self) -> DataGetter["EquipORM"]: ...

    @property
    def gem_category(self) -> DataGetter["GemCategoryORM"]: ...

    @property
    def mintmark(self) -> DataGetter["MintmarkORM"]: ...

    @property
    def mintmark_class(self) -> DataGetter["MintmarkClassCategoryORM"]: ...

    @property
    def custom_mintmark_series(self) -> DataResolver["MintmarkORM"]: ...

    @property
    def pet(self) -> DataGetter["PetORM"]: ...

    @property
    def pet_skin(self) -> DataGetter["PetSkinORM"]: ...

    @property
    def suit(self) -> DataGetter["SuitORM"]: ...

    @property
    def title(self) -> DataGetter["TitlePartORM"]: ...

    @property
    def type_combination(self) -> DataGetter["TypeCombinationORM"]: ...

    def query(self, operation: DataQuery[_T]) -> AbstractContextManager[_T]: ...

    def resolve(
        self,
        getter: DataResolver[_T],
        arg: str,
    ) -> AbstractContextManager[tuple[_T, ...]]: ...

    def get(
        self,
        getter: DataGetter[_T],
        id_: int,
    ) -> AbstractContextManager[_T | None]: ...

    def get_many(
        self,
        getter: DataGetter[_T],
        ids: set[int],
    ) -> AbstractContextManager[dict[int, _T]]: ...

    def pet_and_skins(
        self,
        arg: str,
    ) -> AbstractContextManager[
        tuple[tuple["PetORM", ...], tuple["PetSkinORM", ...]]
    ]: ...

    def mintmark_query(
        self,
        arg: str,
    ) -> AbstractContextManager[tuple["MintmarkORM", ...]]: ...
