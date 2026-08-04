# SPDX-License-Identifier: MIT
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.integrations.seer_data.pet_display_data import (
    load_pet_derived_display_data,
)
from ironsbot.services.seer.rendering.custom_pet_info import (
    _extract_soulmark,
    _format_analyze_desc,
)
from ironsbot.services.seer.rendering.pet_effect_presentation import (
    assign_special_effect_colors,
)

SARMON_PET_ID = 3549
SARMON_STATUS_ID = 188
BASE_SOULMARK_ID = 9
UPGRADED_SOULMARK_ID = 10
SOULMARK_ICON_ID = 32
REPEATED_EFFECT_COUNT = 2


def _create_published_fact_tables(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE pet_special_effect (
                pet_id INTEGER NOT NULL,
                effect_key TEXT NOT NULL,
                glossary_id INTEGER,
                status_id INTEGER,
                sort_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                PRIMARY KEY (pet_id, effect_key)
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TABLE pet_special_effect_source (
                pet_id INTEGER NOT NULL,
                effect_key TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                resolution_rule TEXT NOT NULL,
                source_detail TEXT
            )
            """
        )
    )
    session.execute(
        text(
            """
            CREATE TABLE pet_soulmark_display (
                pet_id INTEGER NOT NULL,
                soulmark_id INTEGER NOT NULL,
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
                pet_id INTEGER NOT NULL,
                soulmark_id INTEGER NOT NULL,
                icon_id INTEGER NOT NULL,
                icon_png BLOB,
                icon_png_available INTEGER NOT NULL,
                icon_png_content_type TEXT
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
                INSERT INTO pet_special_effect
                    (
                        pet_id, effect_key, glossary_id, status_id, sort_id,
                        name, description
                    )
                VALUES
                    (3549, 'glossary:535', 535, NULL, 535, '八方圻', '八方圻说明'),
                    (3549, 'glossary:533', 533, 188, 533, '四象门', '四象门说明'),
                    (3549, 'glossary:534', 534, NULL, 534, '六芒阵', '六芒阵说明')
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO pet_special_effect_source
                    (
                        pet_id, effect_key, source_kind, source_id,
                        resolution_rule, source_detail
                    )
                VALUES
                    (
                        3549, 'glossary:533', 'skill', 17448,
                        'highlight_exact', '繁苍解道'
                    ),
                    (3549, 'glossary:534', 'glossary_link', 533, 'official_link', NULL),
                    (3549, 'glossary:535', 'glossary_link', 533, 'official_link', NULL)
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO pet_soulmark_display (pet_id, soulmark_id, display_order)
                VALUES (3549, 10, 2), (3549, 9, 1)
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO soulmark_icon
                    (
                        pet_id, soulmark_id, icon_id, icon_png,
                        icon_png_available, icon_png_content_type
                    )
                VALUES
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
    assert display.special_effects[1].sources == ("官方词条关联",)
    assert display.soulmark_display_order == {
        BASE_SOULMARK_ID: 1,
        UPGRADED_SOULMARK_ID: 2,
    }
    assert display.soulmark_icons[BASE_SOULMARK_ID].icon_id == SOULMARK_ICON_ID
    assert display.soulmark_icons[BASE_SOULMARK_ID].png == b"published-png"
    assert UPGRADED_SOULMARK_ID not in display.soulmark_icons


def test_effect_colors_reuse_official_highlights_with_default() -> None:
    pet = SimpleNamespace(
        soulmark=[SimpleNamespace(analyze_desc="[color=#57c975]支援[/color]")],
        skill_links=[
            SimpleNamespace(
                skill=SimpleNamespace(
                    info="",
                    skill_effect=[
                        SimpleNamespace(
                            analyze_info="[color=#52a5f2]蓝色词条[/color]",
                            info="",
                        )
                    ],
                    friend_skill_effect=[],
                    hide_effect=None,
                )
            )
        ],
    )
    effects: list[dict[str, Any]] = [
        {"name": "支援"},
        {"name": "蓝色词条"},
        {"name": "无色词条"},
    ]

    assign_special_effect_colors(cast("Any", pet), cast("Any", effects))

    assert [effect["color"] for effect in effects] == [
        "#57c975",
        "#52a5f2",
        "#f35555",
    ]


def test_plain_effect_mentions_are_highlighted_every_time() -> None:
    rendered = _format_analyze_desc(
        "六芒阵与八方圻，六芒阵再次出现",
        {"六芒阵": "#f35555", "八方圻": "#f35555"},
    )

    assert (
        rendered.count('style="color:#f35555">六芒阵</b>')
        == REPEATED_EFFECT_COUNT
    )
    assert rendered.count('style="color:#f35555">八方圻</b>') == 1


def test_soulmark_formatting_keeps_official_colors_and_order() -> None:
    base = SimpleNamespace(
        id=2,
        analyze_desc="",
        desc="plain description",
        desc_formatting_adjustment=(
            "<indent=0><sprite=0><indent=16>获得"
            "<color=#FFF779>不破诛罚</color>\r\n"
            "<indent=16><sprite=3><indent=32>并"
            "<color=#64F9FA>恢复</color><b>体力</b>"
        ),
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )
    upgraded = SimpleNamespace(
        **{**base.__dict__, "id": 3, "analyze_desc": "强化魂印"}
    )

    rendered = _extract_soulmark(
        cast("Any", [upgraded, base]),
        display_order={2: 1, 3: 2},
    )

    assert [soulmark["id"] for soulmark in rendered] == [2, 3]
    assert 'style="color:#FFF779">不破诛罚</b>' in rendered[0]["desc"]
    assert 'style="color:#64F9FA">恢复</b>' in rendered[0]["desc"]
    assert "<indent=" not in rendered[0]["desc"]
    assert "<sprite=" not in rendered[0]["desc"]
