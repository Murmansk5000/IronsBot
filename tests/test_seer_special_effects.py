# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.pet_display_data import (
    load_pet_derived_display_data,
)
from ironsbot.services.seer.rendering.analyze_description import (
    format_analyze_description,
)
from ironsbot.services.seer.rendering.pet_effect_presentation import (
    assign_special_effect_colors,
)
from ironsbot.services.seer.rendering.pet_info_models import PetSoulmarkSnapshot
from ironsbot.services.seer.rendering.pet_info_presentation import (
    _format_soulmark_description,
)

EXPECTED_LIUMANGZHEN_HIGHLIGHT_COUNT = 2

SARMON_PET_ID = 3549
SARMON_STATUS_ID = 188
BASE_SOULMARK_ID = 9
UPGRADED_SOULMARK_ID = 10
SOULMARK_ICON_ID = 32


def _create_published_fact_tables(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE pet_special_effect (
                pet_id INTEGER NOT NULL, effect_key TEXT NOT NULL,
                glossary_id INTEGER, status_id INTEGER, sort_id INTEGER,
                name TEXT NOT NULL, description TEXT,
                PRIMARY KEY (pet_id, effect_key)
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TABLE pet_special_effect_source (
                pet_id INTEGER NOT NULL, effect_key TEXT NOT NULL,
                source_kind TEXT NOT NULL, source_id INTEGER NOT NULL,
                resolution_rule TEXT NOT NULL, source_detail TEXT
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TABLE pet_soulmark_display (
                pet_id INTEGER NOT NULL, soulmark_id INTEGER NOT NULL,
                display_order INTEGER NOT NULL,
                PRIMARY KEY (pet_id, soulmark_id)
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TABLE soulmark_icon (
                pet_id INTEGER NOT NULL, soulmark_id INTEGER NOT NULL,
                icon_id INTEGER NOT NULL, icon_png BLOB,
                icon_png_available INTEGER NOT NULL, icon_png_content_type TEXT
            )
            """
        )
    )


def test_published_effect_facts_keep_sarmon_links_and_prebuilt_icons() -> None:
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        _create_published_fact_tables(session)
        session.execute(
            text(
                """
                INSERT INTO pet_special_effect VALUES
                (3549, 'glossary:535', 535, NULL, 535, '八方圻', '八方圻说明'),
                (3549, 'glossary:533', 533, 188, 533, '四象门', '四象门说明'),
                (3549, 'glossary:534', 534, NULL, 534, '六芒阵', '六芒阵说明')
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO pet_special_effect_source VALUES
                (3549, 'glossary:533', 'skill', 17448, 'highlight_exact', '繁苍解道'),
                (3549, 'glossary:534', 'glossary_link', 533, 'official_link', NULL),
                (3549, 'glossary:535', 'glossary_link', 533, 'official_link', NULL)
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO pet_soulmark_display VALUES (3549, 10, 2), (3549, 9, 1)
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO soulmark_icon VALUES
                (3549, 9, 32, :png, 1, 'image/png'),
                (3549, 10, 33, NULL, 0, 'image/png')
                """
            ),
            {"png": b"published-png"},
        )
        session.commit()
        display = load_pet_derived_display_data(
            session,
            pet_id=SARMON_PET_ID,
            soulmark_ids=(BASE_SOULMARK_ID, UPGRADED_SOULMARK_ID),
        )

    assert [effect.name for effect in display.special_effects] == [
        "四象门",
        "六芒阵",
        "八方圻",
    ]
    assert display.special_effects[0].status_id == SARMON_STATUS_ID
    assert display.special_effects[0].sources == ("技能·繁苍解道",)
    assert display.soulmark_order_by_id == {
        BASE_SOULMARK_ID: 1,
        UPGRADED_SOULMARK_ID: 2,
    }
    icon = display.soulmark_icon_by_id[BASE_SOULMARK_ID]
    assert (icon.icon_id, icon.png) == (SOULMARK_ICON_ID, b"published-png")
    assert UPGRADED_SOULMARK_ID not in display.soulmark_icon_by_id


def test_effect_colors_reuse_official_highlights_with_default() -> None:
    effects: list[dict[str, Any]] = [
        {"name": "支援"},
        {"name": "蓝色词条"},
        {"name": "无色词条"},
    ]

    assign_special_effect_colors(
        effects,  # type: ignore[arg-type]
        ("[color=#57c975]支援[/color]", "[color=#52a5f2]蓝色词条[/color]"),
    )

    assert [effect["color"] for effect in effects] == [
        "#57c975",
        "#52a5f2",
        "#f35555",
    ]


def test_presentation_formats_plain_mentions_and_unity_soulmark_markup() -> None:
    rendered = format_analyze_description(
        "六芒阵与八方圻，六芒阵再次出现",
        {"六芒阵": "#f35555", "八方圻": "#f35555"},
    )
    assert (
        rendered.count('style="color:#f35555">六芒阵</b>')
        == EXPECTED_LIUMANGZHEN_HIGHLIGHT_COUNT
    )
    assert rendered.count('style="color:#f35555">八方圻</b>') == 1

    soulmark = PetSoulmarkSnapshot(
        id=2,
        desc="plain description",
        analyze_desc=None,
        formatting_adjustment=(
            "<indent=0><sprite=0><indent=16>获得"
            "<color=#FFF779>不破诛罚</color>\r\n"
            "<indent=16><sprite=3><indent=32>并"
            "<color=#64F9FA>恢复</color><b>体力</b>"
        ),
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tags=(),
    )
    description = _format_soulmark_description(soulmark, {})

    assert 'style="color:#FFF779">不破诛罚</b>' in description
    assert 'style="color:#64F9FA">恢复</b>' in description
    assert "<indent=" not in description
    assert "<sprite=" not in description
