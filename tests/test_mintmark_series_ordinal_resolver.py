from types import SimpleNamespace

import nonebot
from pytest import MonkeyPatch
from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import MintmarkMaxAttrORM, UniversalPartORM
from sqlmodel import Session, SQLModel, create_engine

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer_data import db
from ironsbot.plugins.seer_data.orm import MintmarkClassAliasORM
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY


def _make_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add_mintmark(  # noqa: PLR0913
    session: Session,
    id_: int,
    name: str,
    class_id: int,
    *,
    connect_id: int | None = None,
    attrs: tuple[int, int, int, int, int, int] | None = None,
) -> None:
    session.add(MintmarkORM(id=id_, name=name, desc="", type_id=3, rarity_id=0))
    max_attr_value = None
    if attrs is not None:
        max_attr_value = MintmarkMaxAttrORM(
            atk=attrs[0],
            def_=attrs[1],
            sp_atk=attrs[2],
            sp_def=attrs[3],
            spd=attrs[4],
            hp=attrs[5],
        )
    session.add(
        UniversalPartORM(
            mintmark_id=id_,
            mintmark_class_id=class_id,
            connect_id=connect_id,
            max_attr_value=max_attr_value,
        )
    )


def _patch_merge_connected(monkeypatch: MonkeyPatch, *, value: bool) -> None:
    monkeypatch.setattr(
        db,
        "get_app_config",
        lambda: SimpleNamespace(
            seer=SimpleNamespace(
                mintmark=SimpleNamespace(merge_connected=value),
            ),
        ),
    )


def test_mintmark_series_ordinal_resolves_class_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    names = [
        "九天之疾",
        "九天之速",
        "九曲之刃",
        "九曲之光",
        "九霄之钟",
    ]
    for offset, name in enumerate(names):
        _add_mintmark(data_session, 41286 + offset, name, 33)
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    data_session.commit()
    alias_session.commit()

    resolver = db.MintmarkSeriesOrdinalResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "九霄05")

    assert [item.id for item in result] == [41290]


def test_mintmark_series_ordinal_uses_merged_connected_order(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=75, name="沧吟星海系列"))
    alias_session.add(MintmarkClassAliasORM(name="k14", target_id=75))
    for offset in range(8):
        _add_mintmark(data_session, 42368 + offset, f"旧{offset + 1}", 75)
    for offset in range(8):
        _add_mintmark(
            data_session,
            45039 + offset,
            f"新{offset + 1}",
            75,
            connect_id=42368 + offset,
        )
    data_session.commit()
    alias_session.commit()

    resolver = db.MintmarkSeriesOrdinalResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "k1405")

    assert [item.id for item in result] == [45043]


def test_mintmark_series_ordinal_is_used_after_mintmark_command_prefix(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    for offset in range(5):
        _add_mintmark(data_session, 41286 + offset, f"九天{offset + 1}", 33)
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    data_session.commit()
    alias_session.commit()

    state = {BOT_COMMAND_ARG_KEY: "九霄05"}
    result = db.MintmarkDataGetter(
        {"seerapi": data_session, "aliases": alias_session},
        state[BOT_COMMAND_ARG_KEY],
    )

    assert [item.id for item in result] == [41290]


def test_mintmark_series_type_resolves_class_alias() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    examples = [
        (41286, "九天之疾", (32, 0, 0, 0, 45, 0)),
        (41287, "九天之速", (0, 0, 32, 0, 45, 0)),
        (41288, "九曲之刃", (60, 0, 0, 0, 0, 0)),
        (41289, "九曲之光", (0, 0, 60, 0, 0, 0)),
        (41290, "九霄之钟", (32, 0, 0, 0, 0, 112)),
        (41291, "九霄之灵", (0, 0, 32, 0, 0, 112)),
        (41292, "九鼎之承", (32, 45, 0, 45, 0, 0)),
        (41293, "九鼎之重", (0, 45, 32, 45, 0, 0)),
    ]
    for id_, name, attrs in examples:
        _add_mintmark(data_session, id_, name, 33, attrs=attrs)
    data_session.commit()
    alias_session.commit()

    resolver = db.MintmarkSeriesTypeResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "九霄盾")

    assert [item.id for item in result] == [41292, 41293]


def test_mintmark_series_type_resolves_short_alias_with_connected_merge(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=75, name="沧吟星海系列"))
    alias_session.add(MintmarkClassAliasORM(name="k14", target_id=75))
    for offset in range(4):
        _add_mintmark(data_session, 42368 + offset, f"旧{offset + 1}", 75)
    for offset, attrs in enumerate(
        [
            (32, 0, 0, 0, 45, 0),
            (0, 0, 32, 0, 45, 0),
            (60, 0, 0, 0, 0, 0),
            (0, 0, 60, 0, 0, 0),
        ]
    ):
        _add_mintmark(
            data_session,
            45039 + offset,
            f"新{offset + 1}",
            75,
            connect_id=42368 + offset,
            attrs=attrs,
        )
    data_session.commit()
    alias_session.commit()

    resolver = db.MintmarkSeriesTypeResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "k14特攻")

    assert [item.id for item in result] == [45042]


def test_mintmark_series_type_getter_uses_mintmark_command_arg() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    _add_mintmark(data_session, 41292, "九鼎之承", 33, attrs=(32, 45, 0, 45, 0, 0))
    data_session.commit()
    alias_session.commit()

    state = {BOT_COMMAND_ARG_KEY: "九霄盾"}
    result = db.MintmarkDataGetter(
        {"seerapi": data_session, "aliases": alias_session},
        state[BOT_COMMAND_ARG_KEY],
    )

    assert [item.id for item in result] == [41292]
