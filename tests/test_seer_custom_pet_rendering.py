# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from pytest import MonkeyPatch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ironsbot.services.seer.pet_partner import (
    PetPartner,
    PetPartnerMember,
    PetPartnerSkill,
    PetPartnerSkillItem,
)
from ironsbot.services.seer.rendering import custom_pet_info
from ironsbot.services.seer.rendering.custom_pet_soulmark_icons import (
    resolve_soulmark_icon_urls,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.rendering import TemplatePath


TEST_SOULMARK_ICON_ID = 1644
TRANSIENT_SOULMARK_ICON_ID = 806


def _soulmark_dict(soulmark_id: int = 100) -> custom_pet_info.SoulmarkDict:
    return {
        "id": soulmark_id,
        "desc": "soulmark",
        "intensified": False,
        "intensified_to_id": None,
        "is_adv": False,
        "pve_effective": None,
        "tags": [],
        "icon_id": None,
        "icon_asset_url": None,
        "icon": None,
    }


class _Stats:
    def to_model(self) -> _Stats:
        return self

    def round(self) -> _Stats:
        return self

    def model_dump(self) -> dict[str, int]:
        return {
            "atk": 1,
            "def_": 1,
            "sp_atk": 1,
            "sp_def": 1,
            "spd": 1,
            "hp": 1,
            "total": 6,
        }


class _GuardedPet:
    def __init__(self, after_await: dict[str, bool]) -> None:
        self._after_await = after_await
        self.id = 1
        self.name = "测试精灵"
        self.resource_id = 1001
        self.gender = SimpleNamespace(id=0)
        self.type = SimpleNamespace(id=1, name="普通")
        self.encyclopedia = None
        self.base_stats = _Stats()
        self.advance = None
        self.skill_links: list[Any] = []
        self.soulmark: list[Any] = []
        self.glossary_entry: list[Any] = []

    def __getattribute__(self, name: str) -> Any:
        guarded = {
            "gender",
            "type",
            "encyclopedia",
            "base_stats",
            "advance",
            "skill_links",
            "soulmark",
            "glossary_entry",
        }
        if name in guarded and object.__getattribute__(self, "_after_await")["started"]:
            raise AssertionError
        return object.__getattribute__(self, name)


class _GuardedMintmark:
    def __init__(self, after_await: dict[str, bool]) -> None:
        self._after_await = after_await
        self.id = 2001
        self.name = "测试刻印"
        self.desc = ""
        self._skills = [SimpleNamespace(name="不存在的技能")]

    @property
    def skill(self) -> list[Any]:
        if self._after_await["started"]:
            raise AssertionError
        return self._skills


class _Session:
    def __init__(self, mintmarks: list[Any]) -> None:
        self._mintmarks = mintmarks

    def execute(self, _statement: object) -> _Session:
        return self

    def scalars(self) -> _Session:
        return self

    def all(self) -> list[Any]:
        return self._mintmarks


class _Cache:
    def get(self, _category: str, _content_key: str) -> None:
        return None

    def put(self, _category: str, _content_key: str, _data: bytes) -> None:
        return None


class _Images:
    def __init__(self, after_await: dict[str, bool]) -> None:
        self._after_await = after_await

    async def fetch(self, _kind: str, _key: str, **_kwargs: object) -> bytes:
        self._after_await["started"] = True
        return b"image"


@pytest.mark.asyncio
async def test_pet_render_snapshots_lazy_relationships_before_image_fetch(
    monkeypatch: MonkeyPatch,
) -> None:
    after_await = {"started": False}
    pet = _GuardedPet(after_await)
    mintmark = _GuardedMintmark(after_await)
    captured: dict[str, object] = {}

    async def render_html(
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        _ = (template_path, template_name, max_width, allow_refit)
        captured["templates"] = templates
        return b"rendered"

    monkeypatch.setattr(
        custom_pet_info,
        "object_session",
        lambda _pet: _Session([mintmark]),
    )
    monkeypatch.setattr(
        custom_pet_info,
        "load_pet_partner",
        lambda _session, _pet_id: None,
    )
    monkeypatch.setattr(
        custom_pet_info,
        "_add_pet_linked_status_effects",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        custom_pet_info,
        "_add_skill_red_effects",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        custom_pet_info,
        "_gender_icon_data_uri",
        lambda _gender_id: "gender",
    )

    result = await custom_pet_info.render_custom_pet_info(
        cast("Any", _Cache()),
        cast("Any", _Images(after_await)),
        render_html,
        cast("Any", pet),
    )

    assert result == b"rendered"
    templates = cast("dict[str, object]", captured["templates"])
    assert templates["pet_name"] == "测试精灵"
    assert templates["skill_marks"] == [
        {
            "id": 2001,
            "name": "测试刻印",
            "desc": "",
            "icon": "data:image/png;base64,aW1hZ2U=",
            "skills": [],
        }
    ]
    assert templates["pet_partner"] is None


def test_build_pet_partner_keeps_skill_activation_item_separate_from_reward(
    monkeypatch: MonkeyPatch,
) -> None:
    partner = PetPartner(
        group_id=15,
        name="源初之夜",
        cost_item_id=1722827,
        cost_item_name="契约徽章",
        cost_item_quantity=8,
        members=(
            PetPartnerMember(pet_id=4329, name="夜魔之神"),
            PetPartnerMember(pet_id=3491, name="魔灵王"),
        ),
        before_description="强化前魂印",
        after_description="强化后魂印",
        skill=PetPartnerSkill(
            skill_id=36696,
            name="至暗·无量空邃",
            activation_item=PetPartnerSkillItem(
                item_id=1725370,
                name="梦夜之源",
                quantity=1,
            ),
        ),
    )
    monkeypatch.setattr(
        custom_pet_info,
        "load_item_exchange_prices",
        lambda _session, _item_ids: {},
    )

    rendered = custom_pet_info._build_pet_partner(partner, object())

    assert rendered is not None
    assert set(rendered) == {"name", "cost_item", "skill"}
    assert rendered["cost_item"] == {
        "id": 1722827,
        "name": "契约徽章",
        "quantity": 8,
        "icon": None,
        "prices": [],
    }
    assert rendered["skill"] == {
        "id": 36696,
        "name": "至暗·无量空邃",
        "activation_item": {
            "id": 1725370,
            "name": "梦夜之源",
            "quantity": 1,
            "icon": None,
            "prices": [],
        },
    }


def test_partition_soulmarks_uses_real_partner_upgrade_without_duplication() -> None:
    partner = PetPartner(
        group_id=15,
        name="源初之夜",
        cost_item_id=1722827,
        cost_item_name="契约徽章",
        cost_item_quantity=8,
        members=(),
        before_description="damage=80; status=base",
        after_description="damage=100; status=upgraded",
        skill=None,
    )
    base_soulmark: custom_pet_info.SoulmarkDict = {
        "id": 100,
        "desc": "damage=80; status=base",
        "intensified": False,
        "intensified_to_id": None,
        "is_adv": False,
        "pve_effective": None,
        "tags": [],
        "icon_id": None,
        "icon_asset_url": None,
        "icon": None,
    }
    upgraded_soulmark: custom_pet_info.SoulmarkDict = {
        **base_soulmark,
        "desc": "damage=100; status=upgraded (boss)",
    }

    base, upgraded = custom_pet_info._partition_soulmarks(
        [base_soulmark, upgraded_soulmark],
        partner,
    )

    assert base == [base_soulmark]
    assert upgraded == [upgraded_soulmark]


def test_partition_soulmarks_uses_official_upgrade_link_before_text_matching() -> None:
    partner = PetPartner(
        group_id=15,
        name="Source Night",
        cost_item_id=1722827,
        cost_item_name="Contract Badge",
        cost_item_quantity=8,
        members=(),
        before_description="old description",
        after_description="new description",
        skill=None,
    )
    base_soulmark: custom_pet_info.SoulmarkDict = {
        "id": 100,
        "desc": "old description",
        "intensified": False,
        "intensified_to_id": 200,
        "is_adv": False,
        "pve_effective": None,
        "tags": [],
        "icon_id": None,
        "icon_asset_url": None,
        "icon": None,
    }
    upgraded_soulmark: custom_pet_info.SoulmarkDict = {
        **base_soulmark,
        "id": 200,
        "desc": "new description",
        "intensified_to_id": None,
    }

    base, upgraded = custom_pet_info._partition_soulmarks(
        [upgraded_soulmark, base_soulmark],
        partner,
    )

    assert base == [base_soulmark]
    assert upgraded == [upgraded_soulmark]


def test_resolve_soulmark_icon_prefers_embedded_png() -> None:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE soulmark_icon (
                    soulmark_id INTEGER NOT NULL,
                    pet_id INTEGER NOT NULL,
                    effect_id INTEGER NOT NULL,
                    icon_id INTEGER NOT NULL,
                    icon_asset_url TEXT,
                    icon_asset_status INTEGER NOT NULL,
                    icon_png BLOB,
                    icon_png_available INTEGER NOT NULL,
                    icon_png_content_type TEXT NOT NULL,
                    PRIMARY KEY (soulmark_id, pet_id, effect_id, icon_id)
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO soulmark_icon
                    (
                        soulmark_id,
                        pet_id,
                        effect_id,
                        icon_id,
                        icon_asset_url,
                        icon_asset_status,
                        icon_png,
                        icon_png_available,
                        icon_png_content_type
                    )
                VALUES
                    (
                        100,
                        4450,
                        2041,
                        :icon_id,
                        :url,
                        200,
                        :png,
                        1,
                        'image/png'
                    )
                """
            ),
            {
                "url": "https://seer.61.com/resource/effectIcon/1644.swf",
                "png": b"\x89PNG\r\n\x1a\nicon",
                "icon_id": TEST_SOULMARK_ICON_ID,
            },
        )
        soulmark = _soulmark_dict(100)

        resolve_soulmark_icon_urls(
            session,
            [soulmark],
            pet_id=4450,
        )

    assert soulmark["icon_id"] == TEST_SOULMARK_ICON_ID
    assert soulmark["icon_asset_url"] is None
    assert soulmark["icon"] == "data:image/png;base64,iVBORw0KGgppY29u"


def test_resolve_soulmark_icon_falls_back_to_legacy_swf_url() -> None:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE soulmark_icon (
                    soulmark_id INTEGER NOT NULL,
                    pet_id INTEGER NOT NULL,
                    effect_id INTEGER NOT NULL,
                    icon_id INTEGER NOT NULL,
                    icon_asset_url TEXT,
                    PRIMARY KEY (soulmark_id, pet_id, effect_id, icon_id)
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO soulmark_icon
                    (soulmark_id, pet_id, effect_id, icon_id, icon_asset_url)
                VALUES (100, 4450, 2041, :icon_id, :url)
                """
            ),
            {
                "url": "https://seer.61.com/resource/effectIcon/1644.swf",
                "icon_id": TEST_SOULMARK_ICON_ID,
            },
        )
        soulmark = _soulmark_dict(100)

        resolve_soulmark_icon_urls(
            session,
            [soulmark],
            pet_id=4450,
        )

    assert soulmark["icon_id"] == TEST_SOULMARK_ICON_ID
    assert soulmark["icon_asset_url"] == (
        "https://seer.61.com/resource/effectIcon/1644.swf"
    )
    assert soulmark["icon"] is None


def test_resolve_soulmark_icon_recovers_url_after_transient_build_failure() -> None:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        session.execute(
            text(
                """
                CREATE TABLE soulmark_icon (
                    soulmark_id INTEGER NOT NULL,
                    pet_id INTEGER NOT NULL,
                    effect_id INTEGER NOT NULL,
                    icon_id INTEGER NOT NULL,
                    icon_asset_url TEXT,
                    icon_asset_status INTEGER NOT NULL,
                    icon_png BLOB,
                    icon_png_available INTEGER NOT NULL,
                    icon_png_content_type TEXT NOT NULL,
                    PRIMARY KEY (soulmark_id, pet_id, effect_id, icon_id)
                )
                """
            )
        )
        session.execute(
            text(
                """
                INSERT INTO soulmark_icon
                    (
                        soulmark_id,
                        pet_id,
                        effect_id,
                        icon_id,
                        icon_asset_url,
                        icon_asset_status,
                        icon_png,
                        icon_png_available,
                        icon_png_content_type
                    )
                VALUES (
                    832,
                    3524,
                    1116,
                    :icon_id,
                    NULL,
                    0,
                    NULL,
                    0,
                    ''
                )
                """
            ),
            {"icon_id": TRANSIENT_SOULMARK_ICON_ID},
        )
        soulmark = _soulmark_dict(832)

        resolve_soulmark_icon_urls(
            session,
            [soulmark],
            pet_id=3524,
        )

    assert soulmark["icon_id"] == TRANSIENT_SOULMARK_ICON_ID
    assert soulmark["icon_asset_url"] == (
        "https://seer.61.com/resource/effectIcon/"
        f"{TRANSIENT_SOULMARK_ICON_ID}.swf"
    )
    assert soulmark["icon"] is None


def test_extract_soulmark_orders_unlinked_4354_variants_old_to_new() -> None:
    newer = SimpleNamespace(
        id=2079,
        analyze_desc="new soulmark",
        desc="",
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )
    older = SimpleNamespace(
        id=1578,
        analyze_desc="old soulmark",
        desc="",
        intensified=False,
        intensified_to_id=None,
        is_adv=False,
        pve_effective=False,
        tag=[],
    )

    soulmarks = custom_pet_info._extract_soulmark(
        [cast("Any", newer), cast("Any", older)]
    )

    assert [soulmark["id"] for soulmark in soulmarks] == [1578, 2079]
