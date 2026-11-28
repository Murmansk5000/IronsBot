from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ironsbot.integrations.seer_data.pet_display_data import (
    _build_effect_views,
    _load_effect_icon_rows,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.pet_info_views import PetEffectIconReference


def test_icon_rows_sort_numerically_and_do_not_guess_missing_refs() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(
            text("""
            CREATE TABLE pet_special_effect_icon_candidate (
                pet_id INTEGER, effect_key TEXT, status_id INTEGER, icon_asset_key TEXT
            )
        """)
        )
        session.execute(
            text("""
            INSERT INTO pet_special_effect_icon_candidate VALUES
            (1, 'g:2', 20, '20'), (1, 'g:2', 3, '3'),
            (1, 'g:2', 1, NULL), (2, 'g:2', 2, '2')
        """)
        )
        session.execute(
            text("""
            CREATE TABLE pet_special_effect_icon (
                pet_id INTEGER, effect_key TEXT, icon_kind TEXT, icon_asset_key TEXT,
                status_id INTEGER, variant_value INTEGER
            )
        """)
        )
        session.execute(
            text("""
            INSERT INTO pet_special_effect_icon VALUES
              (1, 'g:1', 'abnormal', '4', NULL, NULL),
              (1, 'g:1', 'sign_buff', '20', 20, NULL),
              (1, 'g:1', 'sign_buff', '3_10', 3, 10),
              (1, 'g:1', 'sign_buff', '3_2', 3, 2),
              (2, 'g:1', 'sign_buff', '1', 1, NULL)
        """)
        )
        icon_rows = _load_effect_icon_rows(session, 1)
    row = {
        "effect_key": "g:1",
        "name": "Known",
        "description": None,
        "glossary_id": 1,
        "status_id": None,
        "display_in_pet_info": 1,
    }
    views = _build_effect_views(
        [
            row,
            {**row, "effect_key": "s:7", "status_id": 7},
            {**row, "effect_key": "g:2"},
            {**row, "display_in_pet_info": 0},
        ],
        {},
        icon_rows,
    )
    assert [view.icon_references for view in views] == [
        (
            ("sign_buff", "3_2"),
            ("sign_buff", "3_10"),
            ("sign_buff", "20"),
            ("abnormal", "4"),
        ),
        (),
        (("sign_buff", "3"), ("sign_buff", "20")),
    ]
    assert views[-1].status_id is None


def test_effect_panel_provenance_can_coexist_with_multiple_icons() -> None:
    references: list[PetEffectIconReference] = [
        ("sign_buff", "137"),
        ("abnormal", "39"),
    ]
    facts = _build_effect_views(
        [
            {
                "effect_key": "s:137",
                "name": "英雄之诫",
                "description": "效果说明",
                "glossary_id": None,
                "status_id": 137,
                "display_in_pet_info": 1,
            }
        ],
        {"s:137": [{"source_kind": "pet_effect_panel", "source_id": 1152}]},
        {"s:137": references},
    )
    assert facts[0].icon_references == tuple(references)
    assert facts[0].sources == ("客户端效果面板",)


@pytest.mark.parametrize(
    ("source_kind", "label"),
    [
        ("client_status_display", "客户端条件显示"),
        ("client_status_variant", "客户端状态分支"),
    ],
)
def test_client_status_source_is_not_labelled_as_skill_or_ownership(
    source_kind: str, label: str
) -> None:
    facts = _build_effect_views(
        [
            {
                "effect_key": "s:161",
                "name": "群芳加护",
                "description": "效果说明",
                "glossary_id": None,
                "status_id": 161,
                "display_in_pet_info": 1,
            }
        ],
        {"s:161": [{"source_kind": source_kind, "source_id": 161}]},
        {},
    )
    assert facts[0].sources == (label,)


@pytest.mark.parametrize("flag", [False, 0, True, 1])
def test_producer_visibility_filters_before_icon_views(flag: object) -> None:
    row: dict[str, object] = {
        "effect_key": "s:999",
        "name": "arbitrary container",
        "description": None,
        "glossary_id": None,
        "status_id": 999,
        "display_in_pet_info": flag,
    }
    child = {
        **row,
        "effect_key": "g:2",
        "name": "actual form",
        "glossary_id": 2,
        "status_id": None,
        "display_in_pet_info": 1,
    }
    views = _build_effect_views([row, child], {}, {"g:2": [("sign_buff", "999")]})
    assert [v.name for v in views] == (
        ["actual form"]
        if flag in (False, 0)
        else ["arbitrary container", "actual form"]
    )
    assert views[-1].icon_references == (("sign_buff", "999"),)


@pytest.mark.parametrize("flag", [None, "0", "false", 2, -1])
def test_malformed_present_visibility_is_not_silently_interpreted(flag: object) -> None:
    with pytest.raises(ValueError, match="display_in_pet_info"):
        _build_effect_views([{"display_in_pet_info": flag}], {}, {})
