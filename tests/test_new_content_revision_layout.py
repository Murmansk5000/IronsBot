from __future__ import annotations

import base64
import io
from dataclasses import replace
from html.parser import HTMLParser

import pytest
from jinja2 import Environment, FileSystemLoader
from PIL import Image

from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.integrations.litehtml import initialize_fontconfig
from ironsbot.integrations.seer_data.new_content_details import NewContentItemDetails
from ironsbot.integrations.seer_data.new_content_renderer import (
    _content_row,
    _fitted_image,
    _initial_rows,
)
from ironsbot.integrations.seer_data.new_content_snapshot import NewContentPreparedItem
from ironsbot.services.seer.new_content import (
    NewContentItem,
    NewContentSnapshot,
    new_content_category_preview_items,
)
from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.new_content import (
    NewContentMenuDocument,
    present_new_content_menu,
    render_new_content_document,
)
from ironsbot.services.seer.rendering.new_content_pool_changes import (
    present_pool_changes,
)

IMAGE_WIDTH = 1080
POOL_PET_COUNT = 40
PET_STATS_ROWS = 3
PET_STATS_COUNT = 6


def _image(size: tuple[int, int], color: str = "#25c496") -> bytes:
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize("size", [(2400, 3600), (3600, 2400), (48, 48)])
@pytest.mark.parametrize("target", [(74, 102), (102, 102), (28, 40), (42, 42)])
def test_thumbnail_fits_without_cropping_or_distorting(
    size: tuple[int, int], target: tuple[int, int]
) -> None:
    uri = _fitted_image(_image(size), target)
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as fitted:
        assert fitted.size == target
        bounds = fitted.getbbox()
        assert bounds is not None
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        assert abs(width - height * size[0] / size[1]) <= 1


def _prepared(item: NewContentItem) -> NewContentPreparedItem:
    return NewContentPreparedItem(
        item,
        NewContentItemDetails(
            metadata="ID", description="完整简介", side_description="完整技能效果"
        ),
        None,
    )


def test_root_preview_is_five_short_rows_and_submenu_has_all_nine() -> None:
    items = tuple(NewContentItem("mintmark", i, f"刻印 {i}", i, {}) for i in range(9))
    snapshot = NewContentSnapshot(
        baseline_established=True,
        config_version="20261030",
        weekly_cycle="2026-10-30",
        items=items,
    )
    previews = new_content_category_preview_items(snapshot, "mintmark", 99)
    rows = _initial_rows(
        snapshot,
        ("mintmark",),
        tuple(map(_prepared, previews)),
        None,
        frozenset({"mintmark"}),
        {},
    )
    assert len(rows) == len(previews) + 1
    assert "9" in rows[0].description
    assert all(row.preview and not row.side_description for row in rows[1:])
    focused = _initial_rows(
        snapshot,
        ("mintmark",),
        tuple(map(_prepared, items)),
        "mintmark",
        frozenset(),
        {},
    )
    assert len(focused) == len(items)
    assert all(not row.preview and row.side_description for row in focused)


def _stress_document() -> NewContentMenuDocument:
    long_text = "https://example.invalid/" + "abcdefgh" * 100
    item = NewContentItem(
        "autocard_chip",
        1,
        "长名称边界验证" * 30,
        1,
        {
            "field_changes_version": 1,
            "field_changes": [
                {
                    "path": ["payload", "description"],
                    "old_exists": True,
                    "new_exists": True,
                    "old": long_text + "\n末行旧效果",
                    "new": long_text + "\n末行新效果",
                },
                {
                    "path": ["payload", "BuffParam"],
                    "old_exists": True,
                    "new_exists": True,
                    "old": "_".join(["1234567890"] * 80),
                    "new": "_".join(["1234567891"] * 80),
                },
            ],
        },
        "modified",
    )
    row = _content_row("1", _prepared(item))
    pets = tuple(
        NewContentItem(
            "peak_pool",
            100 + i,
            "头像",
            i,
            {"previous_limit": 0, "current_limit": 2},
            "modified",
        )
        for i in range(POOL_PET_COUNT)
    )
    uri = _fitted_image(_image((42, 42)), (42, 42))
    pool = present_pool_changes(
        "peak_pool", pets, {("peak_pool", pet.entity_id): uri for pet in pets}
    )
    pool_row = replace(
        row,
        code="b",
        name="竞技池变化",
        is_category=True,
        description="40 只",
        diff_fields=(),
        pool_preview=pool,
    )
    skill_row = replace(
        row,
        code="2",
        name="长技能验证",
        diff_fields=(),
        skill={
            "id": 1,
            "name": "超长技能名称" * 20,
            "type_id": 1,
            "type_name": "草",
            "category_id": 1,
            "category_name": "物理攻击",
            "power": 100,
            "max_pp": 10,
            "accuracy": 100,
            "crit_rate": None,
            "priority": 0,
            "must_hit": False,
            "info": long_text,
            "learning_level": None,
            "is_special": False,
            "is_advanced": False,
            "is_fifth": False,
            "effects": [{"id": 1, "info": long_text}],
            "activation_item": None,
            "friend_bonus": False,
            "hide_effect_desc": long_text,
        },
    )
    icon = _fitted_image(_image((32, 32), "#999999"), (32, 32))
    return present_new_content_menu("2026-10-30", [row, skill_row, pool_row], {1: icon})


@pytest.mark.asyncio
async def test_native_long_text_and_dense_pool_stay_inside_image() -> None:
    initialize_fontconfig()
    raw = await render_new_content_document(render_html_template, _stress_document())
    with Image.open(io.BytesIO(raw)).convert("RGB") as image:
        assert image.width == IMAGE_WIDTH
        # Any painted text/image in these margins indicates clipping, not wrapping.
        for box in ((0, 0, 24, image.height), (1056, 0, 1080, image.height)):
            assert set(image.crop(box).get_flattened_data()) == {(7, 20, 38)}
        pixels = image.get_flattened_data()
        green = [pixel == (37, 196, 150) for pixel in pixels]
        rectangles = sum(
            1
            for i, present in enumerate(green)
            if present
            and (i < image.width or not green[i - image.width])
            and (i % image.width == 0 or not green[i - 1])
        )
        assert rectangles == POOL_PET_COUNT


def test_wrap_spans_keep_text_intact_and_never_hide_overflow() -> None:
    env = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    html = env.get_template("template.html.j2").render(**_stress_document().templates)
    assert "overflow: hidden" not in html
    assert "text-overflow: ellipsis" not in html
    assert "diff-table" not in html
    assert "<del>" in html and "<ins>" in html

    class Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    text = Text()
    text.feed(html)
    restored = "".join(text.parts)
    assert "长名称边界验证" * 30 in restored
    assert "https://example.invalid/" + "abcdefgh" * 100 in restored


def pet_header_document(name: str = "测试精灵") -> NewContentMenuDocument:
    """Synthetic weekly pet fixture shared by native tests and visual QA."""
    item = NewContentItem(
        "pet",
        90001,
        name,
        1,
        {
            "field_changes_version": 1,
            "field_changes": [
                {
                    "path": ["soulmarks", "id=638", "analyze_desc"],
                    "old_exists": True,
                    "new_exists": True,
                    "old": "[sprite name=dot1]攻击结束时附加20点"
                    "[color=#52a5f2]固定伤害[/color]",
                    "new": "[sprite name=dot4]攻击结束时附加30点"
                    "[color=#57c975]固定伤害[/color]"
                    "|[spritename=dot1]首次死亡时复活自身，复活后威力翻倍",
                }
            ],
        },
        "modified",
    )
    details = NewContentItemDetails(
        metadata="ID：90001｜合成排版样例",
        description="简介应位于头像及种族值下方，不被头部遮挡，也不再被全宽属性表隔开。",
        stats=(
            ("攻击", "136"),
            ("防御", "115"),
            ("特攻", "70"),
            ("特防", "115"),
            ("速度", "130"),
            ("体力", "160"),
        ),
        stats_layout="pet_header",
        stats_total="726",
    )
    row = _content_row("1", NewContentPreparedItem(item, details, None))
    avatar = _fitted_image(_image((110, 110)), (110, 110))
    return present_new_content_menu(
        "排版验证",
        [replace(row, image=avatar)],
        {},
        menu_title="周更排版验证（合成样本）",
    )


def test_pet_stats_only_appear_in_three_header_rows_and_not_preview() -> None:
    env = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    document = pet_header_document()
    template = env.get_template("template.html.j2")
    html = template.render(**document.templates)
    assert html.count('class="pet-stats"') == 1
    assert html.count('class="pet-stat-row"') == PET_STATS_ROWS
    assert html.count('class="pet-stat"') == PET_STATS_COUNT
    assert 'class="stat-grid two-column"' not in html
    assert html.index('class="pet-stats"') < html.index('class="item-body"')
    for row in (
        replace(document.items[0], preview=True),
        replace(document.items[0], stats=(), stats_total=""),
    ):
        other = replace(document, items=(row,))
        assert 'class="pet-stats"' not in template.render(**other.templates)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["测试精灵", "九字名字精灵测试甲", "超长名字边界验证" * 8]
)
async def test_native_pet_stats_paint_in_avatar_header_right_side(name: str) -> None:
    initialize_fontconfig()
    raw = await render_new_content_document(
        render_html_template, pet_header_document(name)
    )
    with Image.open(io.BytesIO(raw)).convert("RGB") as image:
        assert image.width == IMAGE_WIDTH
        avatar_mask = Image.new("1", image.size)
        avatar_mask.putdata(
            [pixel == (37, 196, 150) for pixel in image.get_flattened_data()]
        )
        stat_mask = Image.new("1", image.size)
        stat_mask.putdata(
            [pixel == (244, 220, 143) for pixel in image.get_flattened_data()]
        )
        avatar, stats = avatar_mask.getbbox(), stat_mask.getbbox()
        assert avatar is not None and stats is not None
        assert stats[0] >= IMAGE_WIDTH - 440
        assert avatar[1] <= stats[1] < stats[3] <= avatar[3]
        assert stats[2] <= IMAGE_WIDTH - 24
        for box in ((0, 0, 24, image.height), (1056, 0, 1080, image.height)):
            assert set(image.crop(box).get_flattened_data()) == {(7, 20, 38)}
