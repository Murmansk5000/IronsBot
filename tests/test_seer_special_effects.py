# SPDX-License-Identifier: MIT
from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text
from sqlmodel import Session, create_engine

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.custom_pet_info import _extract_soulmark
from ironsbot.services.seer.rendering.custom_pet_special_effects import (
    GLOSSARY_SOURCE,
    SKILL_SOURCE_PREFIX,
    SOULMARK_STATUS_SOURCE_PREFIX,
    STATUS_NAME_SOURCE,
    STATUS_SOURCE,
    _add_named_status_icons,
    _add_pet_linked_status_effects,
    _add_skill_red_effects,
    _add_soulmark_highlight_status_effects,
    _extract_special_effects,
)

if TYPE_CHECKING:
    from ironsbot.services.seer.rendering.custom_pet_models import SpecialEffectDict

EXPECTED_SOULMARK_COUNT = 2
GOLDEN_VISION_STATUS_ID = 178
KNIGHT_DUEL_LOST_BASE_STATUS_ID = 183
KNIGHT_DUEL_LOST_UPGRADED_STATUS_ID = 184


def _template() -> Any:
    environment = Environment(
        loader=FileSystemLoader([CUSTOM_PET_INFO_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    return environment.get_template("template.html.j2")


def _template_context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "pet_name": "test-pet",
        "pet_id": 1,
        "pet_gender_id": 0,
        "pet_gender_icon": "gender.png",
        "pet_type_id": 1,
        "pet_type_name": "test-type",
        "pet_head_img": "head.png",
        "pet_body_img": "body.png",
        "type_icons": {1: "type.png", "prop": "prop.png"},
        "pet_introduction": "",
        "stats": {
            "atk": 1,
            "def_": 1,
            "sp_atk": 1,
            "sp_def": 1,
            "spd": 1,
            "hp": 1,
            "total": 6,
        },
        "advance_stats": None,
        "base_soulmarks": [],
        "upgraded_soulmarks": [],
        "pet_partner": None,
        "special_effects": [],
        "skill_marks": [],
        "fifth_skills": [],
        "advanced_skills": [],
        "special_skills": [],
        "level_skills": [],
    }
    context.update(overrides)
    return context


def _soulmark(description: str, *, intensified: bool) -> dict[str, Any]:
    return {
        "id": 1,
        "desc": description,
        "intensified": intensified,
        "intensified_to_id": None,
        "is_adv": False,
        "pve_effective": None,
        "tags": [],
        "icon_id": None,
        "icon_asset_url": None,
        "icon": None,
    }


def test_special_effects_include_only_direct_glossary_entries() -> None:
    pet = SimpleNamespace(
        glossary_entry=[
            SimpleNamespace(name="direct-effect", desc="direct description"),
        ],
        soulmark=[
            SimpleNamespace(analyze_desc="[color=#f35555]untrusted[/color]", desc="")
        ],
        skill_links=[],
    )

    effects = _extract_special_effects(cast("Any", pet))

    assert effects == [
        {
            "name": "direct-effect",
            "desc": "direct description",
            "sources": [GLOSSARY_SOURCE],
            "icon_id": None,
            "icon": None,
        }
    ]


def test_special_effects_do_not_infer_from_soulmark_or_skill_text() -> None:
    pet = SimpleNamespace(
        glossary_entry=[],
        soulmark=[
            SimpleNamespace(
                analyze_desc="[color=#f35555]untrusted[/color]",
                desc="global-effect",
            )
        ],
        skill_links=[
            SimpleNamespace(
                skill=SimpleNamespace(
                    id=1,
                    name="global-effect",
                    info="untrusted",
                    skill_effect=[],
                    friend_skill_effect=[],
                    hide_effect=None,
                )
            )
        ],
    )

    assert _extract_special_effects(cast("Any", pet)) == []


def test_skill_red_effects_restore_exact_official_terms_only() -> None:
    session = SimpleNamespace(
        execute=lambda _statement: SimpleNamespace(
            all=lambda: [
                ("冥妖之悼", "冥妖之悼的官方说明"),
                ("幽迹之秘", "幽迹之秘的官方说明"),
                ("星执者", "不应凭普通文本命中"),
            ]
        )
    )

    pet = SimpleNamespace(
        glossary_entry=[],
        soulmark=[
            SimpleNamespace(
                analyze_desc="[color=#f35555]星执者[/color]",
                desc="",
            )
        ],
        skill_links=[
            SimpleNamespace(
                skill=SimpleNamespace(
                    id=29402,
                    name="黄泉妖偈",
                    info="普通文本里提到星执者",
                    skill_effect=[
                        SimpleNamespace(
                            analyze_info=(
                                "[color=#f35555]冥妖之悼[/color]"
                                "[color=#f35555]幽迹之秘[/color]"
                            ),
                            info="",
                        ),
                        SimpleNamespace(
                            analyze_info=(
                                "[color=#f35555]星执者的其他句子[/color]"
                            ),
                            info="",
                        ),
                    ],
                    friend_skill_effect=[],
                    hide_effect=None,
                )
            )
        ],
    )
    effects = _extract_special_effects(cast("Any", pet))
    _add_skill_red_effects(cast("Any", session), cast("Any", pet), effects)

    assert effects == [
        {
            "name": "冥妖之悼",
            "desc": "冥妖之悼的官方说明",
            "sources": [f"{SKILL_SOURCE_PREFIX}黄泉妖偈"],
            "icon_id": None,
            "icon": None,
        },
        {
            "name": "幽迹之秘",
            "desc": "幽迹之秘的官方说明",
            "sources": [f"{SKILL_SOURCE_PREFIX}黄泉妖偈"],
            "icon_id": None,
            "icon": None,
        },
    ]


def test_special_effect_statuses_require_a_direct_pet_binding() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE special_effect_status (
                    status_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    show_monster_id INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO special_effect_status
                    (status_id, name, description, show_monster_id, updated_at)
                VALUES
                    (33, 'direct-effect', 'status description', 4911, 0),
                    (34, 'status-only', 'status-only description', 4911, 0),
                    (35, 'global-only', 'global description', 0, 0),
                    (36, 'other-pet', 'other description', 5000, 0)
                """
            )
        )

    pet = SimpleNamespace(
        glossary_entry=[
            SimpleNamespace(name="direct-effect", desc="glossary description"),
        ],
        soulmark=[],
        skill_links=[],
    )
    effects = _extract_special_effects(cast("Any", pet))

    with Session(engine) as session:
        _add_pet_linked_status_effects(session, effects, pet_id=4911)

    assert effects == [
        {
            "name": "direct-effect",
            "desc": "glossary description",
            "sources": [GLOSSARY_SOURCE, STATUS_SOURCE],
            "icon_id": 33,
            "icon": None,
        },
        {
            "name": "status-only",
            "desc": "status-only description",
            "sources": [STATUS_SOURCE],
            "icon_id": 34,
            "icon": None,
        },
    ]


def test_unique_named_status_adds_icon_to_trusted_effect() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE special_effect_status (
                    status_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    show_monster_id INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO special_effect_status
                    (status_id, name, description, show_monster_id, updated_at)
                VALUES
                    (178, '黄金万象', 'status description', 0, 0),
                    (183, '骑士决斗·落败', 'same', 0, 0),
                    (184, '骑士决斗·落败', 'same', 0, 0)
                """
            )
        )

    effects: list[SpecialEffectDict] = [
        {
            "name": "黄金万象",
            "desc": "glossary description",
            "sources": [GLOSSARY_SOURCE],
            "icon_id": None,
            "icon": None,
        },
        {
            "name": "骑士决斗·落败",
            "desc": "ambiguous",
            "sources": [GLOSSARY_SOURCE],
            "icon_id": None,
            "icon": None,
        },
    ]

    with Session(engine) as session:
        _add_named_status_icons(session, effects)

    assert effects[0]["icon_id"] == GOLDEN_VISION_STATUS_ID
    assert STATUS_NAME_SOURCE in effects[0]["sources"]
    assert effects[1]["icon_id"] is None


def test_green_soulmark_highlight_matches_status_by_description() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE special_effect_status (
                    status_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    show_monster_id INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO special_effect_status
                    (status_id, name, description, show_monster_id, updated_at)
                VALUES
                    (:base_id, :name, :base_desc, 0, 0),
                    (:upgraded_id, :name, :upgraded_desc, 0, 0)
                """
            ),
            {
                "base_id": 107,
                "upgraded_id": 113,
                "name": "支援",
                "base_desc": "伤害不低于300；附加100点护盾；恢复最大体力的30%",
                "upgraded_desc": (
                    "伤害不低于350；附加140点护盾；"
                    "恢复最大体力的35%；天命之耀"
                ),
            },
        )

    pet = SimpleNamespace(
        soulmark=[
            SimpleNamespace(
                id=1901,
                desc="伤害不低于300，附加100点护盾，恢复最大体力的30%",
                analyze_desc="[color=#57c975]支援[/color]",
                desc_formatting_adjustment="",
            ),
            SimpleNamespace(
                id=1940,
                desc="伤害不低于350，附加140点护盾，恢复最大体力的35%，天命之耀",
                analyze_desc="[color=#57c975]支援[/color]",
                desc_formatting_adjustment="",
            ),
        ]
    )
    effects: list[Any] = []

    with Session(engine) as session:
        _add_soulmark_highlight_status_effects(session, cast("Any", pet), effects)

    assert effects == [
        {
            "name": "支援",
            "desc": "伤害不低于300；附加100点护盾；恢复最大体力的30%",
            "sources": [f"{SOULMARK_STATUS_SOURCE_PREFIX}1901"],
            "icon_id": 107,
            "icon": None,
        },
        {
            "name": "支援",
            "desc": "伤害不低于350；附加140点护盾；恢复最大体力的35%；天命之耀",
            "sources": [f"{SOULMARK_STATUS_SOURCE_PREFIX}1940"],
            "icon_id": 113,
            "icon": None,
        },
    ]


def test_same_status_description_falls_back_to_lowest_status_id() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE special_effect_status (
                    status_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    show_monster_id INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO special_effect_status
                    (status_id, name, description, show_monster_id, updated_at)
                VALUES
                    (:upgraded_status_id, '骑士决斗·落败', :desc, 0, 0),
                    (:base_status_id, '骑士决斗·落败', :desc, 0, 0)
                """
            ),
            {
                "base_status_id": KNIGHT_DUEL_LOST_BASE_STATUS_ID,
                "upgraded_status_id": KNIGHT_DUEL_LOST_UPGRADED_STATUS_ID,
                "desc": (
                    "己方危机感+1；自身击败对手的回合无法触发击败类效果"
                )
            },
        )

    pet = SimpleNamespace(
        soulmark=[
            SimpleNamespace(
                id=2099,
                desc="骑士决斗·落败",
                analyze_desc="[color=#f35555]骑士决斗·落败[/color]",
                desc_formatting_adjustment="",
            ),
        ]
    )
    effects: list[Any] = []

    with Session(engine) as session:
        _add_soulmark_highlight_status_effects(session, cast("Any", pet), effects)

    assert effects[0]["icon_id"] == KNIGHT_DUEL_LOST_BASE_STATUS_ID


def test_soulmark_does_not_repeat_glossary_descriptions() -> None:
    soulmark = SimpleNamespace(
        id=1,
        analyze_desc="[color=#f35555]direct-effect[/color]",
        desc="direct-effect",
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )

    rendered = _extract_soulmark([cast("Any", soulmark)])

    assert "glossaries" not in rendered[0]


def test_soulmark_formatting_description_keeps_official_yellow() -> None:
    soulmark = SimpleNamespace(
        id=1,
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

    rendered = _extract_soulmark([cast("Any", soulmark)])

    assert 'style="color:#FFF779">不破诛罚</b>' in rendered[0]["desc"]
    assert 'style="color:#64F9FA">恢复</b>' in rendered[0]["desc"]
    assert "<indent=" not in rendered[0]["desc"]
    assert "<sprite=" not in rendered[0]["desc"]
    assert "<b>" not in rendered[0]["desc"]


def test_soulmark_prefers_analyze_description_over_long_formatting() -> None:
    soulmark = SimpleNamespace(
        id=1,
        analyze_desc="[color=#f35555]短版机制[/color]",
        desc="plain description",
        desc_formatting_adjustment=(
            "<indent=0><sprite=0><indent=16>"
            "<color=#FFF779>很长的U端机制</color>"
        ),
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )

    rendered = _extract_soulmark([cast("Any", soulmark)])

    assert "短版机制" in rendered[0]["desc"]
    assert "很长的U端机制" not in rendered[0]["desc"]


def test_special_effect_template_shows_icon_and_card_style() -> None:
    html = _template().render(
        **_template_context(
            special_effects=[
                {
                    "name": "direct-effect",
                    "desc": "direct description",
                    "sources": [GLOSSARY_SOURCE],
                    "icon_id": 33,
                    "icon": "data:image/png;base64,aW1hZ2U=",
                }
            ]
        )
    )

    assert "direct-effect" in html
    assert "direct description" in html
    assert 'class="special-effect-icon"' in html
    assert 'src="data:image/png;base64,aW1hZ2U="' in html
    special_effect_css = html.split(".special-effect {", maxsplit=1)[1].split(
        "}", maxsplit=1
    )[0]
    assert "background-color: #2a5a9a;" in special_effect_css
    assert "border-left: 4px solid #ffffff;" in special_effect_css


def test_special_effect_template_preserves_description_newlines() -> None:
    html = _template().render(
        **_template_context(
            special_effects=[
                {
                    "name": "direct-effect",
                    "desc": "first line\nsecond line",
                    "sources": [GLOSSARY_SOURCE],
                    "icon_id": None,
                    "icon": None,
                }
            ]
        )
    )

    special_effect_desc_css = html.split(
        ".special-effect-desc {", maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "white-space: pre-line;" in special_effect_desc_css
    assert "first line\nsecond line" in html


def test_partner_upgrade_template_places_partner_header_once() -> None:
    html = _template().render(
        **_template_context(
            base_soulmarks=[_soulmark("base", intensified=False)],
            upgraded_soulmarks=[_soulmark("upgraded", intensified=True)],
            pet_partner={
                "name": "partner-upgrade",
                "cost_item": {
                    "id": 1,
                    "name": "contract-item",
                    "quantity": 8,
                    "icon": None,
                    "prices": [],
                },
                "skill": {
                    "id": 2,
                    "name": "partner-skill",
                    "activation_item": {
                        "id": 3,
                        "name": "skill-item",
                        "quantity": 1,
                        "icon": None,
                        "prices": [],
                    },
                },
            },
        )
    )

    assert html.count('class="sm-item"') == EXPECTED_SOULMARK_COUNT
    assert html.count('class="sm-upgrade-title"') == 1
    assert html.index("base") < html.index("partner-upgrade") < html.index("upgraded")
    assert "contract-item" in html
    assert "skill-item" in html
