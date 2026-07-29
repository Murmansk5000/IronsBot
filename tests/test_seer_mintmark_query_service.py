from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import MintmarkMaxAttrORM, UniversalPartORM
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.config.models.seer import MintmarkQueryConfig
from ironsbot.integrations.db_registry import DatabaseManager
from ironsbot.integrations.seer_data.database import SeerDatabase
from ironsbot.services.seer import mintmark as mintmark_module
from ironsbot.services.seer.data import SEERAPI_DB
from ironsbot.services.seer.mintmark import (
    MintmarkQueryService,
    MintmarkQueryView,
    build_mintmark_views,
    format_mintmark_choice_description,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource

NEW_MINTMARK_ID = 45001
OLD_MINTMARK_ID = 41606


class FakeData:
    mintmark = object()
    gem_category = object()

    def __init__(self) -> None:
        self.mintmarks: tuple[Any, ...] = ()
        self.categories: tuple[Any, ...] = ()
        self.session_active = False

    @contextmanager
    def mintmark_query(
        self,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.session_active = True
        try:
            yield self.mintmarks
        finally:
            self.session_active = False

    @contextmanager
    def resolve(
        self,
        _getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.session_active = True
        try:
            yield self.categories
        finally:
            self.session_active = False


class FakeImages:
    async def fetch(
        self,
        kind: object,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert kind == "mintmark"
        assert fallback is False
        return f"image:{key}".encode()


def _service(data: FakeData) -> MintmarkQueryService:
    return MintmarkQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages()),
        merge_connected=True,
    )

def test_mintmark_query_config_merges_connected_by_default() -> None:
    assert MintmarkQueryConfig().merge_connected is True


@pytest.mark.asyncio
async def test_mintmark_formats_relationships_before_session_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = FakeData()
    mintmark = SimpleNamespace(id=45001, name="十年·筑梦")
    data.mintmarks = (mintmark,)

    def build_views(
        _mintmarks: Any,
        *,
        merge_connected: bool,
    ) -> tuple[MintmarkQueryView, ...]:
        assert merge_connected
        return (MintmarkQueryView(cast("MintmarkORM", mintmark)),)

    def format_details(
        _view: MintmarkQueryView,
        *,
        merge_connected: bool,
    ) -> str:
        assert merge_connected
        assert data.session_active
        return "会话内格式化"

    monkeypatch.setattr(mintmark_module, "build_mintmark_views", build_views)
    monkeypatch.setattr(
        mintmark_module,
        "_format_mintmark_details",
        format_details,
    )

    result = await _service(data).search_mintmark("十年")

    assert result.reply is not None
    assert result.reply.image == b"image:45001"
    assert result.reply.text == "会话内格式化"
    assert data.session_active is False


@pytest.mark.asyncio
async def test_gem_formats_relationships_before_session_closes() -> None:
    data = FakeData()

    class SessionBoundGemCategory:
        id = 1
        name = "绝命"
        generation_id = 1

        @property
        def gem(self) -> list[Any]:
            assert data.session_active
            return [
                SimpleNamespace(
                    level=1,
                    skill_effect_in_use=[SimpleNamespace(info="附加伤害")],
                )
            ]

    data.categories = (SessionBoundGemCategory(),)

    result = await _service(data).search_gem("绝命")

    assert result.reply is not None
    assert "附加伤害" in result.reply.text
    assert data.session_active is False


def _connected_mintmark_session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(MintmarkClassCategoryORM(id=100, name="十周年系列"))
    session.add_all(
        (
            MintmarkORM(
                id=OLD_MINTMARK_ID,
                name="十年·筑梦",
                desc="",
                type_id=3,
                rarity_id=0,
            ),
            MintmarkORM(
                id=NEW_MINTMARK_ID,
                name="十年·筑梦",
                desc="",
                type_id=3,
                rarity_id=0,
            ),
            UniversalPartORM(
                mintmark_id=OLD_MINTMARK_ID,
                mintmark_class_id=100,
                max_attr_value=MintmarkMaxAttrORM(
                    atk=32,
                    def_=0,
                    sp_atk=0,
                    sp_def=0,
                    spd=45,
                    hp=0,
                ),
            ),
            UniversalPartORM(
                mintmark_id=NEW_MINTMARK_ID,
                mintmark_class_id=100,
                connect_id=OLD_MINTMARK_ID,
                max_attr_value=MintmarkMaxAttrORM(
                    atk=32,
                    def_=0,
                    sp_atk=0,
                    sp_def=0,
                    spd=45,
                    hp=0,
                ),
            ),
        )
    )
    session.commit()
    return session


def test_connected_mintmarks_merge_keeps_new_record_and_orders_root_id_first() -> None:
    session = _connected_mintmark_session()
    old = session.get(MintmarkORM, OLD_MINTMARK_ID)
    new = session.get(MintmarkORM, NEW_MINTMARK_ID)
    assert old is not None and new is not None

    views_from_old_id = build_mintmark_views(
        (old,),
        merge_connected=True,
    )
    views_from_new_id = build_mintmark_views(
        (new,),
        merge_connected=True,
    )

    for views in (views_from_old_id, views_from_new_id):
        assert len(views) == 1
        assert views[0].mintmark.id == NEW_MINTMARK_ID
        assert views[0].related_ids == (OLD_MINTMARK_ID,)
        assert views[0].ids == (OLD_MINTMARK_ID, NEW_MINTMARK_ID)
        assert format_mintmark_choice_description(
            views[0],
            merge_connected=True,
        ).startswith("41606、45001")


def test_connected_mintmarks_remain_separate_when_merge_disabled() -> None:
    session = _connected_mintmark_session()
    old = session.get(MintmarkORM, OLD_MINTMARK_ID)
    new = session.get(MintmarkORM, NEW_MINTMARK_ID)
    assert old is not None and new is not None

    views = build_mintmark_views(
        (new, old),
        merge_connected=False,
    )

    assert [view.mintmark.id for view in views] == [
        NEW_MINTMARK_ID,
        OLD_MINTMARK_ID,
    ]
    assert format_mintmark_choice_description(
        views[0],
        merge_connected=False,
    ).startswith(
        "45001，关联41606"
    )
    assert format_mintmark_choice_description(
        views[1],
        merge_connected=False,
    ).startswith(
        "41606，关联45001"
    )


@pytest.mark.asyncio
async def test_mintmark_series_query_preloads_connected_relationships() -> None:
    databases = DatabaseManager()
    databases.register(SEERAPI_DB)
    engine = databases.get_engine(SEERAPI_DB)
    assert engine is not None
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(MintmarkClassCategoryORM(id=100, name="十周年系列"))
        session.add_all(
            (
                MintmarkORM(
                    id=OLD_MINTMARK_ID,
                    name="十年·筑梦",
                    desc="",
                    type_id=3,
                    rarity_id=0,
                ),
                MintmarkORM(
                    id=NEW_MINTMARK_ID,
                    name="十年·筑梦",
                    desc="",
                    type_id=3,
                    rarity_id=0,
                ),
                UniversalPartORM(
                    mintmark_id=OLD_MINTMARK_ID,
                    mintmark_class_id=100,
                    max_attr_value=MintmarkMaxAttrORM(
                        atk=32,
                        def_=0,
                        sp_atk=0,
                        sp_def=0,
                        spd=45,
                        hp=0,
                    ),
                ),
                UniversalPartORM(
                    mintmark_id=NEW_MINTMARK_ID,
                    mintmark_class_id=100,
                    connect_id=OLD_MINTMARK_ID,
                    max_attr_value=MintmarkMaxAttrORM(
                        atk=32,
                        def_=0,
                        sp_atk=0,
                        sp_def=0,
                        spd=45,
                        hp=0,
                    ),
                ),
            )
        )
        session.commit()

    data = SeerDatabase(databases, merge_connected_mintmarks=True)
    with data.mintmark_query("十年") as mintmarks:
        assert [mintmark.id for mintmark in mintmarks] == [
            OLD_MINTMARK_ID,
            NEW_MINTMARK_ID,
        ]
        loaded = mintmarks

    views = build_mintmark_views(loaded, merge_connected=True)

    assert len(views) == 1
    assert views[0].mintmark.id == NEW_MINTMARK_ID
    assert views[0].related_ids == (OLD_MINTMARK_ID,)
    assert views[0].ids == (OLD_MINTMARK_ID, NEW_MINTMARK_ID)

    service = MintmarkQueryService(
        data,
        cast("SeerImageSource", FakeImages()),
        merge_connected=True,
    )
    search_result = await service.search_mintmark("十年")
    selection_result = await service.select_mintmark(OLD_MINTMARK_ID)

    for result in (search_result, selection_result):
        assert result.reply is not None
        assert result.reply.image == b"image:45001"
        assert "41606、45001" in result.reply.text
