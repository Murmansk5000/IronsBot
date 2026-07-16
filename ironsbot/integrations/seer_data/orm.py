# SPDX-License-Identifier: MIT
from abc import ABC, abstractmethod

from sqlalchemy.orm import declared_attr
from sqlmodel import Field, SQLModel


class BaseAliasORM(SQLModel, ABC):
    name: str = Field(primary_key=True)
    target_id: int = Field(primary_key=True)

    @declared_attr  # pyright: ignore[reportArgumentType]
    def __tablename__(cls) -> str:  # noqa: N805  # pyright: ignore[reportIncompatibleVariableOverride]
        return cls.table_name()

    @classmethod
    @abstractmethod
    def table_name(cls) -> str:
        raise NotImplementedError


class PetAliasORM(BaseAliasORM, table=True):
    @classmethod
    def table_name(cls) -> str:
        return "pet_aliases"


class MintmarkAliasORM(BaseAliasORM, table=True):
    @classmethod
    def table_name(cls) -> str:
        return "mintmark_aliases"


class MintmarkClassAliasORM(BaseAliasORM, table=True):
    @classmethod
    def table_name(cls) -> str:
        return "mintmark_class_aliases"


class MintmarkSeriesMemberORM(BaseAliasORM, table=True):
    @classmethod
    def table_name(cls) -> str:
        return "mintmark_series_members"


class GemAliasORM(BaseAliasORM, table=True):
    @classmethod
    def table_name(cls) -> str:
        return "gem_aliases"
