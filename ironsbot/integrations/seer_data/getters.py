# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from seerapi_models import (
    BattleEffectORM,
    ElementTypeORM,
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
from sqlmodel import and_, or_, select

from ironsbot.services.seer.data import SEERAPI_DB

from .mintmark_series_resolvers import MintmarkSeriesResolver
from .normalization import strip_special as _strip_special
from .orm import (
    MintmarkAliasORM,
    MintmarkClassAliasORM,
    PetAliasORM,
)
from .resolvers import AliasResolver, Getter, IdResolver, NameResolver

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.services.seer.data import SessionMap

logger = logging.getLogger(__name__)

PetDataGetter = Getter(
    PetORM,
    IdResolver(PetORM),
    NameResolver(PetORM),
    AliasResolver(PetORM, PetAliasORM),
)

def build_mintmark_data_getter(
    *,
    merge_connected: bool,
) -> Getter[MintmarkORM]:
    return Getter(
        MintmarkORM,
        IdResolver(MintmarkORM),
        NameResolver(MintmarkORM),
        AliasResolver(MintmarkORM, MintmarkAliasORM),
        MintmarkSeriesResolver(merge_connected=merge_connected),
    )

MintmarkClassDataGetter = Getter(
    MintmarkClassCategoryORM,
    # IdResolver(MintmarkClassCategoryORM),
    NameResolver(MintmarkClassCategoryORM),
    AliasResolver(MintmarkClassCategoryORM, MintmarkClassAliasORM),
)

PetSkinDataGetter = Getter(
    PetSkinORM,
    IdResolver(PetSkinORM),
    NameResolver(PetSkinORM),
)

GemCategoryDataGetter = Getter(
    GemCategoryORM,
    # IdResolver(GemCategoryORM),
    NameResolver(GemCategoryORM),
)

SuitDataGetter = Getter(
    SuitORM,
    IdResolver(SuitORM),
    NameResolver(SuitORM),
)

EquipDataGetter = Getter(
    EquipORM,
    IdResolver(EquipORM),
    NameResolver(EquipORM),
)

TitleDataGetter = Getter(
    TitlePartORM,
    IdResolver(TitlePartORM),
    NameResolver(TitlePartORM),
)

class TypeCombinationResolver:
    """将用户输入拆分为单属性名，再按 ID 组合查询 TypeCombinationORM。

    支持任意顺序输入：如 "火战斗" 和 "战斗火" 都能匹配到同一条双属性记录。
    """

    __slots__ = ("db_name",)

    def __init__(self, *, db_name: str = SEERAPI_DB) -> None:
        self.db_name = db_name

    def __call__(self, sessions: SessionMap, arg: str) -> Iterable[TypeCombinationORM]:
        session = sessions.get(self.db_name)
        if session is None:
            logger.warning("TypeCombinationResolver: 未找到数据库会话")
            return ()

        stripped = _strip_special(arg)
        if not stripped:
            return ()

        all_types = session.exec(select(ElementTypeORM)).all()
        name_to_id: dict[str, int] = {t.name: t.id for t in all_types}

        # 单属性：整个输入是一个合法属性名
        if stripped in name_to_id:
            tid = name_to_id[stripped]
            results = list(
                session.exec(
                    select(TypeCombinationORM).where(
                        TypeCombinationORM.primary_id == tid,
                        TypeCombinationORM.secondary_id is None,
                    )
                ).all()
            )
            if results:
                return results

        # 双属性：尝试在每个位置拆分为两个合法属性名
        found: dict[int, TypeCombinationORM] = {}
        for i in range(1, len(stripped)):
            left, right = stripped[:i], stripped[i:]
            if left not in name_to_id or right not in name_to_id:
                continue
            a, b = name_to_id[left], name_to_id[right]
            combos = session.exec(
                select(TypeCombinationORM).where(
                    or_(
                        and_(
                            TypeCombinationORM.primary_id == a,
                            TypeCombinationORM.secondary_id == b,
                        ),
                        and_(
                            TypeCombinationORM.primary_id == b,
                            TypeCombinationORM.secondary_id == a,
                        ),
                    )
                )
            ).all()
            for combo in combos:
                found.setdefault(combo.id, combo)

        return tuple(found.values())


TypeCombinationDataGetter = Getter(
    TypeCombinationORM,
    IdResolver(TypeCombinationORM),
    NameResolver(TypeCombinationORM),
    TypeCombinationResolver(),
)

BattleEffectDataGetter = Getter(
    BattleEffectORM,
    IdResolver(BattleEffectORM),
    NameResolver(BattleEffectORM),
)
