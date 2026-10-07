# SPDX-License-Identifier: MIT
from collections.abc import Iterator

import pytest
from seerapi_models import MintmarkClassCategoryORM
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.integrations.seer_data.orm import MintmarkClassAliasORM
from ironsbot.integrations.seer_data.resolvers import (
    AliasResolver,
    Getter,
    IdResolver,
    NameResolver,
)


@pytest.fixture
def matching_session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                MintmarkClassCategoryORM(id=1, name="星光"),
                MintmarkClassCategoryORM(id=2, name="星光之影"),
                MintmarkClassCategoryORM(id=3, name="晨曦"),
                MintmarkClassCategoryORM(id=4, name="Bonus%Up"),
                MintmarkClassCategoryORM(id=5, name="BonusXUp"),
                MintmarkClassAliasORM(name="星光", target_id=3),
                MintmarkClassAliasORM(name="星光别名", target_id=3),
                MintmarkClassAliasORM(name="星光影子", target_id=2),
                MintmarkClassAliasORM(name="Reward%Up", target_id=4),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def _getter() -> Getter[MintmarkClassCategoryORM]:
    return Getter(
        MintmarkClassCategoryORM,
        IdResolver(MintmarkClassCategoryORM),
        NameResolver(MintmarkClassCategoryORM),
        AliasResolver(MintmarkClassCategoryORM, MintmarkClassAliasORM),
    )


def test_sql_exact_names_and_aliases_share_priority_and_deduplicate(
    matching_session: Session,
) -> None:
    sessions = {"seerapi": matching_session, "aliases": matching_session}
    getter = _getter()
    assert [item.id for item in getter(sessions, "星光")] == [1, 3]
    assert {item.id for item in getter(sessions, "光")} == {1, 2, 3}
    assert [item.id for item in getter(sessions, "3")] == [3]
    assert not getter(sessions, "999")


def test_sql_partial_queries_do_not_treat_percent_as_a_wildcard(
    matching_session: Session,
) -> None:
    sessions = {"seerapi": matching_session, "aliases": matching_session}
    getter = _getter()
    assert [item.id for item in getter(sessions, "%")] == [4]
    assert [item.id for item in getter(sessions, "REWARD%")] == [4]
    for query in ("", " _ - · / ", "星光之影没拿好也是卒"):
        assert not getter(sessions, query)
