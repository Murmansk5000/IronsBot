import os
from pathlib import Path

import nonebot
from pytest import MonkeyPatch
from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import MintmarkMaxAttrORM, UniversalPartORM
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.config.loader import clear_app_config_cache
from ironsbot.config.models.seer import MintmarkQueryConfig

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")
clear_app_config_cache()

NEW_MINTMARK_ID = 45001
OLD_MINTMARK_ID = 41606

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer.query.commands import mintmark_handlers


def test_mintmark_query_config_merges_connected_by_default() -> None:
    assert MintmarkQueryConfig().merge_connected is True


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


def test_connected_mintmarks_merge_into_new_record(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mintmark_handlers,
        "get_mintmark_query_config",
        lambda: MintmarkQueryConfig(merge_connected=True),
    )
    session = _connected_mintmark_session()
    old = session.get(MintmarkORM, OLD_MINTMARK_ID)
    new = session.get(MintmarkORM, NEW_MINTMARK_ID)
    assert old is not None and new is not None

    views_from_old_id = mintmark_handlers._build_mintmark_views((old,))
    views_from_new_id = mintmark_handlers._build_mintmark_views((new,))

    for views in (views_from_old_id, views_from_new_id):
        assert len(views) == 1
        assert views[0].mintmark.id == NEW_MINTMARK_ID
        assert views[0].related_ids == (OLD_MINTMARK_ID,)
        assert mintmark_handlers._item_desc_fmt(views[0]).startswith("45001、41606")


def test_connected_mintmarks_remain_separate_when_merge_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mintmark_handlers,
        "get_mintmark_query_config",
        lambda: MintmarkQueryConfig(merge_connected=False),
    )
    session = _connected_mintmark_session()
    old = session.get(MintmarkORM, OLD_MINTMARK_ID)
    new = session.get(MintmarkORM, NEW_MINTMARK_ID)
    assert old is not None and new is not None

    views = mintmark_handlers._build_mintmark_views((new, old))

    assert [view.mintmark.id for view in views] == [
        NEW_MINTMARK_ID,
        OLD_MINTMARK_ID,
    ]
    assert mintmark_handlers._item_desc_fmt(views[0]).startswith(
        "45001，关联41606"
    )
    assert mintmark_handlers._item_desc_fmt(views[1]).startswith(
        "41606，关联45001"
    )
