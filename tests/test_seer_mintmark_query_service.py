from seerapi_models import MintmarkClassCategoryORM, MintmarkORM
from seerapi_models.mintmark import MintmarkMaxAttrORM, UniversalPartORM
from sqlmodel import Session, SQLModel, create_engine

from ironsbot.config.models.seer import MintmarkQueryConfig
from ironsbot.services.seer.mintmark import (
    build_mintmark_views,
    format_mintmark_choice_description,
)

NEW_MINTMARK_ID = 45001
OLD_MINTMARK_ID = 41606

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


def test_connected_mintmarks_merge_into_new_record() -> None:
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
        assert format_mintmark_choice_description(
            views[0],
            merge_connected=True,
        ).startswith("45001、41606")


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
