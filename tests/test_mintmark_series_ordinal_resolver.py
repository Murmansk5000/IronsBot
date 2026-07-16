import nonebot
import pytest
from pytest import MonkeyPatch
from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import MintmarkMaxAttrORM, UniversalPartORM
from sqlmodel import Session, SQLModel, create_engine

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.seer import MintmarkQueryConfig
from ironsbot.integrations.seer_data import getters, mintmark_series_resolvers
from ironsbot.integrations.seer_data.orm import (
    MintmarkClassAliasORM,
    MintmarkSeriesMemberORM,
)
from ironsbot.utils.rule import BOT_COMMAND_ARG_KEY
from tests.helpers.config import stub_app_config


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
    universal_part = UniversalPartORM(
        mintmark_id=id_,
        mintmark_class_id=class_id,
        connect_id=connect_id,
    )
    if max_attr_value is not None:
        universal_part.max_attr_value = max_attr_value
    session.add(universal_part)


def _patch_merge_connected(monkeypatch: MonkeyPatch, *, value: bool) -> None:
    monkeypatch.setattr(
        mintmark_series_resolvers,
        "get_app_config",
        lambda: stub_app_config(
            mintmark_config=MintmarkQueryConfig(merge_connected=value),
        ),
    )


@pytest.fixture(autouse=True)
def _patch_default_mintmark_config(monkeypatch: MonkeyPatch) -> None:
    _patch_merge_connected(monkeypatch, value=True)


def test_mintmark_series_ordinal_resolves_class_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    names = [
        ("九天之疾", (32, 0, 0, 0, 45, 0)),
        ("九天之速", (0, 0, 32, 0, 45, 0)),
        ("九曲之刃", (60, 0, 0, 0, 0, 0)),
        ("九曲之光", (0, 0, 60, 0, 0, 0)),
        ("九霄之钟", (32, 0, 0, 0, 0, 112)),
    ]
    for offset, (name, attrs) in enumerate(names):
        _add_mintmark(data_session, 41286 + offset, name, 33, attrs=attrs)
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "九霄05")

    assert [item.id for item in result] == [41290]


def test_custom_mintmark_series_resolves_exact_ordinal_and_type() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=100, name="十周年系列"))
    for offset, attrs in enumerate(
        (
            (32, 0, 0, 0, 45, 0),
            (0, 0, 32, 0, 45, 0),
            (60, 0, 0, 0, 0, 0),
        )
    ):
        mintmark_id = 45001 + offset
        _add_mintmark(
            data_session,
            mintmark_id,
            f"十年{offset + 1}",
            100,
            attrs=attrs,
        )
        alias_session.add(
            MintmarkSeriesMemberORM(name="十年", target_id=mintmark_id)
        )
    data_session.commit()
    alias_session.commit()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [
        item.id
        for item in mintmark_series_resolvers.resolve_custom_mintmark_series(
            sessions, "十年"
        )
    ] == [45001, 45002, 45003]
    assert [
        item.id
        for item in mintmark_series_resolvers.resolve_custom_mintmark_series(
            sessions, "十年02"
        )
    ] == [45002]
    assert [
        item.id
        for item in mintmark_series_resolvers.resolve_custom_mintmark_series(
            sessions, "十年物速"
        )
    ] == [45001]


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
    for offset, attrs in enumerate(
        [
            (32, 0, 0, 0, 45, 0),
            (0, 0, 32, 0, 45, 0),
            (60, 0, 0, 0, 0, 0),
            (0, 0, 60, 0, 0, 0),
            (32, 0, 0, 0, 0, 112),
            (0, 0, 32, 0, 0, 112),
            (32, 45, 0, 45, 0, 0),
            (0, 45, 32, 45, 0, 0),
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

    resolver = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "k1405")

    assert [item.id for item in result] == [45043]


def test_mintmark_series_ordinal_uses_stat_based_slots(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    examples = [
        (41286, "九天之疾", (32, 0, 0, 0, 45, 0)),
        (41287, "九天之速", (0, 0, 32, 0, 45, 0)),
        (41288, "九曲之刃", (60, 0, 0, 0, 0, 0)),
        (41289, "九曲之光", (0, 0, 60, 0, 0, 0)),
        (41290, "九霄之钟", (32, 0, 0, 0, 0, 112)),
        (41291, "九霄之灵", (0, 0, 32, 0, 0, 112)),
        (41292, "九鼎之承", (32, 45, 0, 45, 0, 0)),
        (41293, "九鼎之重", (0, 45, 32, 45, 0, 0)),
        (41294, "九天双攻体", (32, 0, 32, 0, 0, 112)),
        (41295, "九天双攻速", (32, 0, 32, 0, 45, 0)),
    ]
    for id_, name, attrs in examples:
        _add_mintmark(data_session, id_, name, 33, attrs=attrs)
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [item.id for item in resolver(sessions, "九霄01")] == [41286]
    assert [item.id for item in resolver(sessions, "九霄02")] == [41287]
    assert [item.id for item in resolver(sessions, "九霄03")] == [41288]
    assert [item.id for item in resolver(sessions, "九霄04")] == [41289]
    assert [item.id for item in resolver(sessions, "九霄05")] == [41290]
    assert [item.id for item in resolver(sessions, "九霄06")] == [41291]
    assert [item.id for item in resolver(sessions, "九霄07")] == [41292]
    assert [item.id for item in resolver(sessions, "九霄08")] == [41293]
    assert [item.id for item in resolver(sessions, "九霄09")] == [41294]
    assert [item.id for item in resolver(sessions, "九霄10")] == [41295]


def test_mintmark_series_ordinal_returns_ties(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=101, name="星璨灵籁系列"))
    examples = [
        (45026, "灵籁一", (32, 45, 0, 45, 26, 112)),
        (45027, "灵籁二", (32, 45, 0, 45, 26, 112)),
        (45028, "灵籁三", (0, 45, 32, 45, 26, 112)),
    ]
    for id_, name, attrs in examples:
        _add_mintmark(data_session, id_, name, 101, attrs=attrs)
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [item.id for item in resolver(sessions, "星璨灵籁01")] == [45026, 45027]
    assert [item.id for item in resolver(sessions, "星璨灵籁07")] == [45026, 45027]


def test_mintmark_series_resolvers_use_unique_partial_class_name(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=71, name="四君子系列"))
    examples = [
        (43001, "四君子物速", (32, 0, 0, 0, 45, 0)),
        (43002, "四君子特速", (0, 0, 32, 0, 45, 0)),
    ]
    for id_, name, attrs in examples:
        _add_mintmark(data_session, id_, name, 71, attrs=attrs)
    data_session.commit()
    alias_session.commit()

    sessions = {"seerapi": data_session, "aliases": alias_session}

    ordinal = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    assert [item.id for item in ordinal(sessions, "君子01")] == [43001]

    series_type = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
    assert [item.id for item in series_type(sessions, "君子速")] == [43001, 43002]


def test_mintmark_series_resolver_ignores_ambiguous_partial_class_name(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=1, name="四君子系列"))
    data_session.add(MintmarkClassCategoryORM(id=2, name="小君子系列"))
    _add_mintmark(data_session, 43001, "四君子物速", 1, attrs=(32, 0, 0, 0, 45, 0))
    _add_mintmark(data_session, 43002, "小君子物速", 2, attrs=(32, 0, 0, 0, 45, 0))
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesOrdinalResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "君子01")

    assert list(result) == []


def test_mintmark_series_ordinal_is_used_after_mintmark_command_prefix(
    monkeypatch: MonkeyPatch,
) -> None:
    _patch_merge_connected(monkeypatch, value=True)
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=33, name="九天系列"))
    for offset, attrs in enumerate(
        [
            (32, 0, 0, 0, 45, 0),
            (0, 0, 32, 0, 45, 0),
            (60, 0, 0, 0, 0, 0),
            (0, 0, 60, 0, 0, 0),
            (32, 0, 0, 0, 0, 112),
        ]
    ):
        _add_mintmark(
            data_session,
            41286 + offset,
            f"九天{offset + 1}",
            33,
            attrs=attrs,
        )
    alias_session.add(MintmarkClassAliasORM(name="九霄系列", target_id=33))
    data_session.commit()
    alias_session.commit()

    state = {BOT_COMMAND_ARG_KEY: "九霄05"}
    result = getters.MintmarkDataGetter(
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

    resolver = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
    result = resolver({"seerapi": data_session, "aliases": alias_session}, "九霄盾")

    assert [item.id for item in result] == [41292, 41293]


def test_mintmark_series_type_resolves_speed_hp_suffix() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=101, name="泳池系列"))
    examples = [
        (45017, "星璨·梦响", (32, 0, 0, 0, 45, 112)),
        (45023, "灵籁·欢夏", (32, 0, 0, 0, 45, 112)),
        (45027, "灵籁·爽夏", (32, 45, 0, 45, 45, 0)),
        (45028, "灵籁·晴夏", (0, 0, 32, 0, 45, 112)),
        (45029, "灵籁·盛夏", (32, 45, 0, 45, 45, 112)),
    ]
    for id_, name, attrs in examples:
        _add_mintmark(data_session, id_, name, 101, attrs=attrs)
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [item.id for item in resolver(sessions, "泳池物速体")] == [
        45017,
        45023,
        45029,
    ]
    assert [item.id for item in resolver(sessions, "泳池物速盾")] == [45027, 45029]
    assert [item.id for item in resolver(sessions, "泳池物盾速体")] == [45029]
    assert [item.id for item in resolver(sessions, "泳池速体")] == [
        45017,
        45023,
        45028,
        45029,
    ]
    assert [item.id for item in resolver(sessions, "泳池双防体")] == [45029]


def test_mintmark_series_type_allows_attack_speed_composite() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=103, name="复合系列"))
    _add_mintmark(
        data_session,
        46010,
        "复合·攻速体",
        103,
        attrs=(60, 0, 0, 0, 45, 112),
    )
    _add_mintmark(
        data_session,
        46011,
        "复合·普通速体",
        103,
        attrs=(32, 0, 0, 0, 45, 112),
    )
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [item.id for item in resolver(sessions, "复合物攻速体")] == [46010]


def test_mintmark_series_type_tries_next_split_when_series_contains_type_word() -> None:
    data_session = _make_session()
    alias_session = _make_session()
    data_session.add(MintmarkClassCategoryORM(id=102, name="攻坚系列"))
    _add_mintmark(data_session, 46001, "攻坚·迅", 102, attrs=(32, 0, 0, 0, 45, 0))
    _add_mintmark(data_session, 46002, "攻坚·守", 102, attrs=(32, 45, 0, 45, 0, 0))
    data_session.commit()
    alias_session.commit()

    resolver = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
    sessions = {"seerapi": data_session, "aliases": alias_session}

    assert [item.id for item in resolver(sessions, "攻坚物速")] == [46001]
    assert [item.id for item in resolver(sessions, "攻坚盾")] == [46002]


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

    resolver = mintmark_series_resolvers.MintmarkSeriesTypeResolver()
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
    result = getters.MintmarkDataGetter(
        {"seerapi": data_session, "aliases": alias_session},
        state[BOT_COMMAND_ARG_KEY],
    )

    assert [item.id for item in result] == [41292]
