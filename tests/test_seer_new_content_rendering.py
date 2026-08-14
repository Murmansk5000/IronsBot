from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.services.seer.autocard import AutocardEntry, AutocardPromptValue
from ironsbot.services.seer.new_content import (
    NewContentCategory,
    NewContentItem,
    NewContentSnapshot,
)
from ironsbot.services.seer.rendering import new_content as new_content_rendering
from ironsbot.services.seer.rendering.new_content import render_new_content_menu
from ironsbot.services.seer.rendering.new_content_pool_changes import (
    pool_change_preview,
)

FLASH_TEST_MOUNT_ID = 1301170
EXPECTED_STANDARD_POOL_CHANGES = 17
EXPERT_POOL_DIRECTION_CHANGES = 5

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


class _Cache:
    def __init__(self) -> None:
        self.saved: bytes | None = None

    def get(self, category: str, key: str) -> bytes | None:
        del category, key
        return None

    def put(self, category: str, key: str, data: bytes) -> None:
        del category, key
        self.saved = data


class _Data:
    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        yield operation(object())  # type: ignore[operator]


class _RichData(_Data):
    pet = object()
    pet_skin = object()
    mintmark = object()
    suit = object()
    equip = object()
    title = object()
    type_combination = object()

    def __init__(
        self,
        records: dict[tuple[object, int], object],
        *,
        skills: dict[int, object] | None = None,
    ) -> None:
        self.records = records
        self.skills = skills or {}

    @contextmanager
    def get(self, getter: object, entity_id: int) -> Iterator[object | None]:
        yield self.records.get((getter, entity_id))

    @contextmanager
    def query(self, operation: object) -> Iterator[object]:
        session = SimpleNamespace(
            get=lambda _model, skill_id: self.skills.get(skill_id),
        )
        yield operation(session)  # type: ignore[operator]


class _Images:
    def __init__(self, *, fail_keys: set[tuple[str, str]] | None = None) -> None:
        self.fail_keys = fail_keys or set()
        self.requests: list[tuple[str, str]] = []

    async def fetch(
        self,
        kind: str,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        del fallback
        self.requests.append((kind, key))
        if (kind, key) in self.fail_keys:
            from ironsbot.services.seer.images import ImageSourceError

            raise ImageSourceError("missing")
        return f"{kind}:{key}".encode()

    async def fetch_url(self, url: str) -> bytes:
        self.requests.append(("url", url))
        return url.encode()


class _Autocard:
    def __init__(
        self,
        entries: dict[tuple[str, int], AutocardEntry] | None = None,
    ) -> None:
        self.entries = entries or {}

    def select(self, value: AutocardPromptValue) -> AutocardEntry:
        if entry := self.entries.get((value.kind, value.item_id)):
            return entry
        item_id = value.item_id
        kind = value.kind
        return AutocardEntry(
            kind=kind,
            item_id=item_id,
            name="测试群星牌",
            text="",
            image_url=f"https://assets.example/{kind}-{item_id}.png",
        )


def _item(
    category: NewContentCategory,
    entity_id: int,
    **payload: Any,
) -> NewContentItem:
    return NewContentItem(
        category=category,
        entity_id=entity_id,
        name=f"条目 {entity_id}",
        sort_value=entity_id,
        payload=payload,
    )


def _attributes() -> SimpleNamespace:
    attributes = SimpleNamespace(
        atk=120,
        sp_atk=100,
        spd=110,
        def_=95,
        sp_def=90,
        hp=135,
        total=650,
    )
    attributes.round = lambda: attributes
    return attributes


@pytest.mark.asyncio
async def test_render_new_content_menu_uses_category_specific_thumbnails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    images = _Images()
    monkeypatch.setattr(
        new_content_rendering,
        "load_skin_image_resolutions",
        lambda _session, _skin_ids: {
            856: SimpleNamespace(head_resource_id=1856),
        },
    )
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260803",
        weekly_cycle="2026-08-03",
        items=(
            _item("pet", 1, resource_id=101),
            _item("pet_skin", 856, resource_id=856),
            _item("mintmark", 2),
            _item("suit", 3),
            _item("equip", 4),
            _item("mount", 5),
            _item("achievement", 6, titles=[{"id": 601, "name": "称号"}]),
            _item("skill", 7),
            _item("autocard_card", 8),
            _item("autocard_role", 9),
            _item("autocard_sanctuary_effect", 10),
        ),
    )
    categories = cast(
        "tuple[NewContentCategory, ...]",
        tuple(item.category for item in snapshot.items),
    )

    rendered_rows: dict[NewContentCategory, Any] = {}
    for category in categories:
        captured.clear()
        result = await render_new_content_menu(
            _Cache(),  # type: ignore[arg-type]
            _Data(),  # type: ignore[arg-type]
            images,  # type: ignore[arg-type]
            _Autocard(),  # type: ignore[arg-type]
            render_html,
            snapshot,
            (category,),
            category,
        )
        assert result == b"menu-image"
        row = captured["items"][0]
        assert row["code"] == "1"
        rendered_rows[category] = row

    assert rendered_rows["pet"]["image"] is not None
    assert rendered_rows["skill"]["image"] is None  # 技能不显示图片
    assert rendered_rows["autocard_sanctuary_effect"]["image"] is None
    assert ("pet_head", "101") in images.requests
    assert ("pet_head", "1856") in images.requests
    assert ("mintmark", "2") in images.requests
    assert ("suit", "3") in images.requests
    assert ("equip", "4") in images.requests
    assert ("equip", "5") in images.requests
    assert ("title", "601") in images.requests
    assert ("url", "https://assets.example/card-8.png") in images.requests
    assert ("url", "https://assets.example/role-9.png") in images.requests


@pytest.mark.asyncio
async def test_render_new_content_menu_keeps_rows_when_an_asset_is_missing() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260803",
        weekly_cycle="2026-08-03",
        items=(_item("mintmark", 2),),
    )
    await render_new_content_menu(
        _Cache(),  # type: ignore[arg-type]
        _RichData({}),  # type: ignore[arg-type]
        _Images(fail_keys={("mintmark", "2")}),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("mintmark",),
        "mintmark",
    )

    item_row = next(row for row in captured["items"] if row["code"] == "1")
    assert item_row["name"] == "条目 2"
    assert item_row["image"] is None


@pytest.mark.asyncio
async def test_missing_mount_image_uses_pending_notice_without_cache() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    cache = _Cache()
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260806",
        weekly_cycle="2026-07-31",
        items=(_item("mount", 1301170),),
    )

    await render_new_content_menu(
        cache,  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(fail_keys={("equip", "1301170")}),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("mount",),
        "mount",
    )

    item_row = next(row for row in captured["items"] if row["code"] == "1")
    assert item_row["image"] is None
    assert item_row["image_notice"] == "官方图片暂未上线"
    assert cache.saved is None


@pytest.mark.asyncio
async def test_missing_unity_mount_image_uses_flash_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    monkeypatch.setattr(
        new_content_rendering,
        "load_flash_mount_image",
        lambda _data, mount_id: (
            b"flash-mount" if mount_id == FLASH_TEST_MOUNT_ID else None
        ),
    )
    cache = _Cache()
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260808",
        weekly_cycle="2026-08-07",
        items=(_item("mount", 1301170),),
    )

    await render_new_content_menu(
        cache,  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(fail_keys={("equip", "1301170")}),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("mount",),
        "mount",
    )

    item_row = next(row for row in captured["items"] if row["code"] == "1")
    assert item_row["image"] == "data:image/png;base64,Zmxhc2gtbW91bnQ="
    assert item_row["image_notice"] == ""
    assert cache.saved == b"menu-image"


@pytest.mark.asyncio
async def test_root_menu_expands_short_categories_with_plain_numeric_codes() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260807",
        weekly_cycle="2026-08-07",
        items=(
            _item("autocard_sanctuary_effect", 1),
            _item("autocard_sanctuary_effect", 2),
            *(_item("skill", 100 + index) for index in range(6)),
        ),
    )

    await render_new_content_menu(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("autocard_sanctuary_effect", "skill"),
        None,
        expanded_categories=frozenset({"autocard_sanctuary_effect"}),
    )

    assert [row["code"] for row in captured["items"]] == ["a", "a1", "a2", "b"]
    assert [row["expanded"] for row in captured["items"] if row["is_category"]] == [
        True,
        False,
    ]
    assert [row["description"] for row in captured["items"] if row["is_category"]] == [
        "2 项新增",
        "6 项新增",
    ]
    assert captured["focused_category"] is None


@pytest.mark.asyncio
async def test_root_render_caps_configured_category_preview_at_five_items() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=tuple(_item("mintmark", index) for index in range(1, 10)),
    )

    await render_new_content_menu(
        _Cache(),  # type: ignore[arg-type]
        _RichData({}),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("mintmark",),
        None,
        expanded_categories=frozenset({"mintmark"}),
        auto_expand_max_items=5,
    )

    assert [row["code"] for row in captured["items"]] == [
        "a",
        "a1",
        "a2",
        "a3",
        "a4",
        "a5",
    ]


def test_new_content_render_cache_key_includes_expanded_categories() -> None:
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260807",
        weekly_cycle="2026-08-07",
        items=(),
    )

    folded = new_content_rendering._cache_key(
        snapshot,
        ("pet", "skill"),
        None,
        "新增内容",
        frozenset(),
        5,
    )
    expanded = new_content_rendering._cache_key(
        snapshot,
        ("pet", "skill"),
        None,
        "新增内容",
        frozenset({"pet"}),
        5,
    )

    assert folded != expanded


@pytest.mark.asyncio
async def test_autocard_root_menu_uses_group_title() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del template_path, template_name, max_width, allow_refit
        captured.update(templates)
        return b"menu-image"

    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260807",
        weekly_cycle="2026-08-07",
        items=(_item("autocard_card", 1),),
    )

    await render_new_content_menu(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,
        snapshot,
        ("autocard_card",),
        None,
        "新增群星牌",
    )

    assert captured["menu_title"] == "新增群星牌"


def test_pet_menu_details_include_icons_intro_and_base_stats() -> None:
    water_type_id = 3
    attributes = _attributes()
    pet = SimpleNamespace(
        id=4926,
        type=SimpleNamespace(id=water_type_id, name="水"),
        gender=SimpleNamespace(id=1, name="雄"),
        encyclopedia=SimpleNamespace(introduction="官方精灵简介"),
        base_stats=SimpleNamespace(to_model=lambda: attributes),
    )
    data = _RichData({(_RichData.pet, 4926): pet})

    details = new_content_rendering._item_details(
        data,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        _item("pet", 4926),
    )

    assert details.metadata == "ID: 4926"
    assert details.description == "官方精灵简介"
    assert details.type_id == water_type_id
    assert details.gender_id == 1
    assert details.type_name == "水"
    assert details.gender_name == "雄"
    assert details.stats == (
        ("攻击", "120"),
        ("防御", "95"),
        ("特攻", "100"),
        ("特防", "90"),
        ("速度", "110"),
        ("体力", "135"),
    )
    assert details.stats_layout == "two_column"
    assert details.stats_total == "650"


def test_peak_pool_preview_places_all_seventeen_changes_in_matrix() -> None:
    transitions = (
        *((0, 2) for _ in range(3)),
        *((2, 0) for _ in range(3)),
        *((2, 3) for _ in range(2)),
        *((3, 2) for _ in range(2)),
        *((3, None) for _ in range(3)),
        (None, 2),
        *((None, 3) for _ in range(3)),
    )
    items = tuple(
        _item(
            "peak_pool",
            index,
            previous_limit=previous,
            current_limit=current,
        )
        for index, (previous, current) in enumerate(transitions, start=1)
    )

    preview = pool_change_preview("peak_pool", items)

    assert preview["title"] == (
        f"竞技池变化｜{EXPECTED_STANDARD_POOL_CHANGES} 只"
    )
    assert preview["headers"] == ("到限0", "到限2", "到限3", "到不限")
    assert tuple(row["label"] for row in preview["matrix_rows"]) == (
        "从限0",
        "从限2",
        "从限3",
        "从不限",
    )
    assert sum(
        len(pets)
        for row in preview["matrix_rows"]
        for pets in row["cells"]
    ) == EXPECTED_STANDARD_POOL_CHANGES
    assert preview["other_rows"] == ()


def test_expert_pool_preview_uses_two_directions_and_keeps_unknown_limits() -> None:
    items = tuple(
        _item(
            "peak_expert_pool",
            index,
            previous_limit=None if index <= EXPERT_POOL_DIRECTION_CHANGES else 0,
            current_limit=0 if index <= EXPERT_POOL_DIRECTION_CHANGES else None,
        )
        for index in range(1, 11)
    )
    unexpected = _item(
        "peak_expert_pool",
        11,
        previous_limit=7,
        current_limit=0,
    )

    preview = pool_change_preview(
        "peak_expert_pool",
        (*items, unexpected),
    )

    assert [row["direction"] for row in preview["direction_rows"]] == [
        "不限 → 限0",
        "限0 → 不限",
    ]
    assert [len(row["pets"]) for row in preview["direction_rows"]] == [
        EXPERT_POOL_DIRECTION_CHANGES,
        EXPERT_POOL_DIRECTION_CHANGES,
    ]
    assert preview["other_rows"][0]["direction"] == "限7 → 限0"
    assert preview["other_rows"][0]["pets"] == (
        {"entity_id": 11, "image": None},
    )


@pytest.mark.asyncio
async def test_pool_render_fetches_pet_heads_without_exposing_names() -> None:
    captured: dict[str, Any] = {}

    async def render_html(
        template_path: object,
        template_name: str,
        templates: Mapping[Any, Any],
        *args: object,
        **kwargs: object,
    ) -> bytes:
        del template_path, template_name, args, kwargs
        captured.update(templates)
        return b"menu-image"

    images = _Images()
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20260814",
        weekly_cycle="2026-08-14",
        items=(
            NewContentItem(
                "peak_pool",
                5000,
                "不应显示的精灵名",
                5000,
                {"previous_limit": 0, "current_limit": 2},
                "modified",
            ),
        ),
    )

    await render_new_content_menu(
        _Cache(),  # type: ignore[arg-type]
        _Data(),  # type: ignore[arg-type]
        images,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        ("peak_pool",),
        None,
    )

    assert images.requests == [("pet_head", "5000")]
    assert "不应显示的精灵名" not in str(captured["items"])
    preview = captured["items"][0]["pool_preview"]
    assert preview["matrix_rows"][0]["cells"][1][0]["image"].startswith(
        "data:image/png;base64,"
    )


def test_skill_menu_details_match_pet_skill_fields() -> None:
    electric_type_id = 5
    expected_power = 150
    expected_pp = 5
    expected_accuracy = 95
    expected_priority = 2
    expected_crit_rate = 25
    effect = SimpleNamespace(effect_id=31, analyze_info="造成固定伤害", info="")
    friend_effect = SimpleNamespace(effect_id=32, analyze_info="恢复自身体力", info="")
    skill = SimpleNamespace(
        skill_effect=[effect],
        friend_skill_effect=[friend_effect],
        hide_effect=SimpleNamespace(description="隐藏效果说明"),
    )
    data = _RichData(
        {
            (
                _RichData.type_combination,
                electric_type_id,
            ): SimpleNamespace(name="电"),
        },
        skills={10001: skill},
    )
    details = new_content_rendering._item_details(
        data,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        _item(
            "skill",
            10001,
            type_id=electric_type_id,
            category_id=1,
            power=expected_power,
            max_pp=expected_pp,
            accuracy=expected_accuracy,
            crit_rate=expected_crit_rate,
            priority=expected_priority,
            atk_num=1,
            info="测试技能效果",
            pets=[{"id": 70, "name": "雷伊"}],
        ),
    )

    assert details.metadata == ""
    assert details.type_id == electric_type_id
    assert details.type_name == "电"
    assert details.description == "关联精灵：雷伊"
    assert details.skill is not None
    assert details.skill["category_name"] == "物理攻击"
    assert details.skill["power"] == expected_power
    assert details.skill["max_pp"] == expected_pp
    assert details.skill["accuracy"] == expected_accuracy
    assert details.skill["priority"] == expected_priority
    assert details.skill["crit_rate"] == expected_crit_rate
    assert details.skill["info"] == "测试技能效果"
    assert details.skill["effects"] == [{"id": 31, "info": "造成固定伤害"}]
    assert details.skill["hide_effect_desc"] == "隐藏效果说明"
    assert details.friend_skill is not None
    assert details.friend_skill["friend_bonus"] is True
    assert details.friend_skill["effects"] == [{"id": 32, "info": "恢复自身体力"}]


def test_skill_menu_details_format_official_rich_text() -> None:
    effect = SimpleNamespace(
        effect_id=31,
        analyze_info=(
            "[sprite name=iconHit]4回合内免疫所有异常状态，"
            "[color=#52a5f2]反弹[/color]所有受到的异常状态"
        ),
        info="",
    )
    skill = SimpleNamespace(
        skill_effect=[effect],
        friend_skill_effect=[],
        hide_effect=None,
    )
    data = _RichData({}, skills={10001: skill})

    details = new_content_rendering._item_details(
        data,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        _item(
            "skill",
            10001,
            info="[sprite name=iconHit]技能说明",
        ),
    )

    assert details.skill is not None
    effect_text = details.skill["effects"][0]["info"]
    assert "[sprite" not in effect_text
    assert "[color" not in effect_text
    assert "[/color]" not in effect_text
    assert "反弹" in effect_text
    assert "color:#52a5f2" in effect_text
    assert details.skill["info"] == "技能说明"


def test_suit_and_equip_menu_details_prefer_official_descriptions() -> None:
    suit = SimpleNamespace(
        id=447,
        suit_desc="晨曦之星战甲官方简介",
        bonus=SimpleNamespace(desc="晨曦之星战甲套装效果"),
    )
    equip = SimpleNamespace(
        id=333,
        part_type=SimpleNamespace(name="头部"),
        suit=SimpleNamespace(name="晨曦之星战甲"),
        bonus=SimpleNamespace(desc="部件官方效果"),
    )
    data = _RichData(
        {
            (_RichData.suit, 447): suit,
            (_RichData.equip, 333): equip,
        }
    )

    suit_details = new_content_rendering._item_details(
        data,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        _item("suit", 447),
    )
    equip_details = new_content_rendering._item_details(
        data,  # type: ignore[arg-type]
        _Autocard(),  # type: ignore[arg-type]
        _item("equip", 333),
    )

    assert suit_details.description == "晨曦之星战甲官方简介"
    assert suit_details.side_title == "套装效果"
    assert suit_details.side_description == "晨曦之星战甲套装效果"
    assert equip_details.metadata == "ID：333｜类型：头部｜套装：晨曦之星战甲"
    assert equip_details.description == "部件官方效果"


def test_autocard_menu_details_keep_intro_left_and_skills_right() -> None:
    role = AutocardEntry(
        kind="role",
        item_id=8,
        name="破界者",
        text="",
        image_url="",
        description="如果界限定义了存在，那么打破界限的人，是在毁灭这个世界，还是在重新定义自己？",
        skill_name="破界",
        skill_text="造成 3 点伤害。",
        skill_upgrade="伤害提升至 5 点。",
    )
    details = new_content_rendering._item_details(
        _Data(),  # type: ignore[arg-type]
        _Autocard({("role", 8): role}),  # type: ignore[arg-type]
        _item("autocard_role", 8),
    )

    assert details.metadata == "ID：8｜角色"
    assert details.description == role.description
    assert details.side_title == "技能：破界"
    assert details.side_description == "造成 3 点伤害。\n升级：伤害提升至 5 点。"


@pytest.mark.asyncio
async def test_sanctuary_images_follow_explicit_pet_or_card_relation() -> None:
    images = _Images()
    card = AutocardEntry(
        kind="card",
        item_id=98,
        name="布布种子",
        text="",
        image_url="https://assets.example/card-98.png",
    )
    autocard = _Autocard({("card", 98): card})

    pet_image = await new_content_rendering._sanctuary_item_image(
        images,  # type: ignore[arg-type]
        autocard,  # type: ignore[arg-type]
        _item("autocard_sanctuary_effect", 1, sanctuary_pet_id=70),
    )
    card_image = await new_content_rendering._sanctuary_item_image(
        images,  # type: ignore[arg-type]
        autocard,  # type: ignore[arg-type]
        _item(
            "autocard_sanctuary_effect",
            2,
            target_type="card",
            target_id=98,
        ),
    )

    assert pet_image is not None
    assert card_image is not None
    assert ("pet_head", "70") in images.requests
    assert ("url", "https://assets.example/card-98.png") in images.requests
