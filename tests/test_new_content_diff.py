from __future__ import annotations

import base64
import io
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageDraw

from ironsbot.integrations.seer_data.new_content_details import NewContentItemDetails
from ironsbot.integrations.seer_data.new_content_renderer import _content_row
from ironsbot.integrations.seer_data.new_content_snapshot import (
    NewContentPreparedItem,
    _autocard_details,
)
from ironsbot.services.seer.autocard import AutocardEntry
from ironsbot.services.seer.new_content import NewContentItem
from ironsbot.services.seer.new_content_diff import FieldDiff, present_field_changes
from ironsbot.services.seer.render_paths import (
    NEW_CONTENT_TEMPLATE_PATH,
    SHARED_TEMPLATE_PATH,
)
from ironsbot.services.seer.rendering.new_content import present_new_content_menu

if TYPE_CHECKING:
    from ironsbot.services.seer.rendering.new_content import NewContentMenuItem


def _change(old: object, new: object, field: str = "description") -> dict:
    return {
        "path": ["payload", field],
        "old_exists": True,
        "new_exists": True,
        "old": old,
        "new": new,
    }


def _item(changes: list[dict]) -> NewContentItem:
    return NewContentItem(
        "autocard_chip",
        90001,
        "测试战斗芯片",
        1,
        {"field_changes_version": 1, "field_changes": changes},
        "modified",
    )


def _version(field: FieldDiff, *, old: bool) -> str:
    excluded = "insert" if old else "delete"
    return "".join(part.text for part in field.fragments if part.kind != excluded)


def test_chinese_diff_highlights_whole_numbers_and_keeps_context() -> None:
    fields, notice = present_field_changes(
        _item([_change("回复20点生命值", "回复30点生命值")])
    )
    assert notice == ""
    assert [(part.text, part.kind) for part in fields[0].fragments] == [
        ("回复", "equal"),
        ("20", "delete"),
        ("30", "insert"),
        ("点生命值", "equal"),
    ]


@pytest.mark.parametrize(
    "before,after",
    [
        (50, 55),
        (20, 30),
        (-50, -55),
        (1.25, 1.75),
        ("50", "55"),
        ("-0.25", "-0.75"),
        ("+20", "+30"),
        (".25", ".75"),
        ("1e-5", "2e-5"),
        ("050", "055"),
    ],
)
def test_numeric_values_are_indivisible(before: object, after: object) -> None:
    fields, notice = present_field_changes(_item([_change(before, after, "health")]))
    assert not notice
    assert [(p.text, p.kind) for p in fields[0].fragments] == [
        (str(before), "delete"),
        (str(after), "insert"),
    ]
    assert _version(fields[0], old=True) == str(before)
    assert _version(fields[0], old=False) == str(after)


def test_multiline_numbers_and_signed_parameters_keep_whole_values() -> None:
    for field, before, after in [
        ("BuffParam", "10_-20_2|1_2", "15_-30_2|1_2"),
        ("skillTxt", "回复20点生命值\n持续2.5回合", "回复30点生命值\n持续3.5回合"),
    ]:
        fields, _ = present_field_changes(_item([_change(before, after, field)]))
        deleted = [p.text for p in fields[0].fragments if p.kind == "delete"]
        inserted = [p.text for p in fields[0].fragments if p.kind == "insert"]
        assert deleted == ([before] if field == "BuffParam" else ["20", "2.5"])
        assert inserted == ([after] if field == "BuffParam" else ["30", "3.5"])
        assert _version(fields[0], old=True) == before
        assert _version(fields[0], old=False) == after


def test_multiline_alignment_keeps_context_and_full_long_text() -> None:
    before = "保持不变\n回复20点\n结束"
    after = "保持不变\n回复30点\n新增效果\n结束"
    fields, _ = present_field_changes(_item([_change(before, after)]))
    assert fields[0].fragments[0].text == "保持不变\n"
    assert fields[0].fragments[0].kind == "equal"
    assert _version(fields[0], old=True) == before
    assert _version(fields[0], old=False) == after
    long = "相同内容" * 1000
    fields, _ = present_field_changes(_item([_change(long + "旧", long + "新")]))
    assert _version(fields[0], old=False) == long + "新"


@pytest.mark.parametrize(
    "old,new", [(None, ""), (0, None), ([], None), (0, "0"), (None, "null")]
)
def test_null_empty_zero_and_scalar_types_remain_distinct(
    old: object, new: object
) -> None:
    fields, _ = present_field_changes(_item([_change(old, new)]))
    assert len(fields) == 1
    assert _version(fields[0], old=True) != _version(fields[0], old=False)


def test_missing_field_is_not_the_same_as_missing_historical_data() -> None:
    change = {
        "path": ["payload", "info"],
        "old_exists": False,
        "new_exists": True,
        "new": "新增效果",
    }
    fields, notice = present_field_changes(_item([change]))
    assert notice == ""
    assert "字段不存在" in _version(fields[0], old=True)
    broken = {**change, "old_exists": True}
    fields, notice = present_field_changes(_item([broken]))
    assert not fields and "旧值未提供" in notice
    legacy = replace(_item([]), payload={"change_summary": ["说明已更新"]})
    assert present_field_changes(legacy) == ((), "旧值未提供，无法对比")


def test_new_and_pool_entries_do_not_get_fake_diff_warnings() -> None:
    assert present_field_changes(replace(_item([]), change_kind="added")) == ((), "")
    assert present_field_changes(replace(_item([]), category="peak_pool")) == ((), "")


def test_compared_effect_is_not_repeated_in_the_current_text() -> None:
    row = _content_row(
        "1",
        NewContentPreparedItem(
            _item([_change("回复20点生命值", "回复30点生命值")]),
            NewContentItemDetails(
                metadata="ID：90001",
                description="",
                side_title="芯片效果",
                side_description="回复30点生命值",
            ),
            None,
        ),
    )
    assert row.side_description == row.side_title == ""
    assert row.diff_fields
    assert row.metadata == "ID：90001"


def test_compared_autocard_effect_keeps_only_unmodified_upgrade_text() -> None:
    item = replace(
        _item([_change("旧效果", "新效果", "skillTxt")]), category="autocard_role"
    )
    details = _autocard_details(
        item,
        AutocardEntry(
            kind="role",
            item_id=41,
            name="百变魔术师",
            text="",
            skill_text="新效果",
            skill_upgrade="未修改升级效果",
            image_key="",
        ),
    )
    assert details.side_description == "升级：未修改升级效果"


def _sample_row(
    item: NewContentItem, details: NewContentItemDetails
) -> NewContentMenuItem:
    return _content_row("1", NewContentPreparedItem(item, details, None))


def sample_diff_html() -> str:
    """Deterministic fictional visual fixture, also usable for screenshot QA."""
    thumbnail = Image.new("RGB", (82, 110), "#305e76")
    draw = ImageDraw.Draw(thumbnail)
    draw.rectangle((12, 14, 70, 96), fill="#4eaf99", outline="#b7e9dc", width=3)
    draw.text((24, 48), "DEMO", fill="white")
    output = io.BytesIO()
    thumbnail.save(output, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    card = _sample_row(
        NewContentItem("autocard_card", 90002, "没有简介的测试卡牌", 2, {}),
        NewContentItemDetails(
            metadata="ID：90002｜卡牌",
            description="",
            side_title="技能：风之守护",
            side_description="己方获得护盾。\n升级：护盾持续时间增加1回合。",
        ),
    )
    card = replace(card, image=image, image_layout="portrait")
    chip = _sample_row(
        _item(
            [
                _change(
                    "每回合回复20点生命值\n持续2回合", "每回合回复30点生命值\n持续3回合"
                ),
                _change(1, 2, "rarity"),
            ]
        ),
        NewContentItemDetails(metadata="修改｜ID：90001｜战斗芯片", description=""),
    )
    skill = _sample_row(
        replace(
            _item(
                [
                    _change(100, 120, "power"),
                    _change("使对手攻击降低1级。", "使对手攻击降低2级。", "info"),
                ]
            ),
            category="skill",
            name="测试技能",
        ),
        NewContentItemDetails(
            metadata="修改｜ID：90003",
            description="关联精灵：测试精灵",
            stats=(("威力", "120"), ("PP", "10")),
            stats_layout="skill",
        ),
    )
    missing = _sample_row(
        replace(_item([]), name="缺少旧版本的条目", payload={}),
        NewContentItemDetails(
            metadata="修改｜ID：90004", description="当前效果正常展示，不猜测旧值。"
        ),
    )
    rows = [
        replace(row, code=str(index))
        for index, row in enumerate((card, chip, skill, missing), start=1)
    ]
    document = present_new_content_menu("2026-10-23", rows, {})
    environment = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    return environment.get_template("template.html.j2").render(**document.templates)


def test_diff_template_escapes_content_and_uses_inline_revisions() -> None:
    row = _sample_row(
        _item([_change("<script>alert(1)</script>", "<b>新效果</b>")]),
        NewContentItemDetails(metadata="ID", description=""),
    )
    document = present_new_content_menu("test", [row], {})
    environment = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH])
    )
    html = environment.get_template("template.html.j2").render(**document.templates)
    assert "<script>" not in html and "<b>新效果</b>" not in html
    assert "&lt;" in html
    assert "<del>" in html and "<ins>" in html
    assert "text-decoration: line-through" in html
    assert "text-decoration: underline" in html
    assert "修改前" not in html and "修改后" not in html
    assert "diff-table" not in html
    assert "flex: 0 0 330px" not in html
    assert "min-height: 100px" not in html


@pytest.mark.parametrize(
    "before,after,has_arrow",
    [(50, 55, True), ("效果", "新增效果", False), ("新增效果", "效果", False)],
)
def test_compact_field_and_display_only_replacement_arrow(
    before: object, after: object, *, has_arrow: bool
) -> None:
    row = _sample_row(
        _item([_change(before, after, "health")]),
        NewContentItemDetails(metadata="ID", description=""),
    )
    document = present_new_content_menu("test", [row], {})
    env = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    html = env.get_template("template.html.j2").render(**document.templates)
    assert (
        '<span class="diff-field">生命值：</span><span class="revision-text">' in html
    )
    arrow = '<span class="revision-arrow" aria-hidden="true"> → </span>'
    assert (arrow in html) is has_arrow
    if has_arrow:
        deleted = "<del><span>50</span></del>"
        inserted = "<ins><span>55</span></ins>"
        assert html.index(deleted) < html.index(arrow) < html.index(inserted)
    field = row.diff_fields[0]
    assert _version(field, old=True) == str(before)
    assert _version(field, old=False) == str(after)


def test_magician_parameters_are_one_complete_replacement() -> None:
    before, after = "1_2_2_2_2_2_2", "1_2_3_3_4_4_2"
    fields, _ = present_field_changes(_item([_change(before, after, "BuffParam")]))
    fragments = fields[0].fragments
    assert [(p.text, p.kind) for p in fragments] == [
        (before, "delete"),
        (after, "insert"),
    ]
    assert _version(fields[0], old=True) == before
    assert _version(fields[0], old=False) == after


@pytest.mark.parametrize("field", ["BuffParam", "buff_param", "buffParam"])
@pytest.mark.parametrize(
    "before,after",
    [
        ("10_-20_2|1_2", "15_-30_2|1_2"),
        ("1_2_2|3_4", "1_2|3_4"),
        ("1_2|3_4", "1_2_2|3_4"),
        ("1_2|3_4", "1_2"),
        ("1_2", "1_2|3_4"),
        ("1__2|", "1_3_2|"),
        ("", "1_2"),
        ("1_2", ""),
        (" 1__2|\r\n3_4 ", " 1__3|\r\n3_4 "),
        ("_".join(["10"] * 500), "_".join(["15"] * 500)),
    ],
)
def test_parameter_revisions_preserve_both_versions(
    before: str, after: str, field: str
) -> None:
    fields, _ = present_field_changes(_item([_change(before, after, field)]))
    old_text, new_text = before or "（空文本）", after or "（空文本）"
    assert [(p.text, p.kind) for p in fields[0].fragments] == [
        (old_text, "delete"),
        (new_text, "insert"),
    ]
    assert _version(fields[0], old=True) == old_text
    assert _version(fields[0], old=False) == new_text


def test_parameter_count_changes_replace_all_groups() -> None:
    fields, _ = present_field_changes(
        _item([_change("1_2_2|3_4", "1_2|3_4", "BuffParam")])
    )
    assert [(p.text, p.kind) for p in fields[0].fragments] == [
        ("1_2_2|3_4", "delete"),
        ("1_2|3_4", "insert"),
    ]


def test_parameter_template_has_exactly_one_replacement_arrow() -> None:
    before, after = "1_2_2_2_2_2_2", "1_2_3_3_4_4_2"
    row = _sample_row(
        _item([_change(before, after, "BuffParam")]),
        NewContentItemDetails(metadata="ID", description=""),
    )
    document = present_new_content_menu("test", [row], {})
    env = Environment(
        loader=FileSystemLoader([NEW_CONTENT_TEMPLATE_PATH, SHARED_TEMPLATE_PATH]),
        autoescape=True,
    )
    template = env.get_template("template.html.j2")
    html = template.render(**document.templates)
    assert html.count('<span class="revision-arrow"') == 1
    bounded_text = vars(template.module)["bounded_text"]
    assert f"<del>{bounded_text(before)}</del>" in html
    assert f"<ins>{bounded_text(after)}</ins>" in html


@pytest.mark.parametrize(
    "before,after",
    [
        ("a\r\nb\r\n", "a\r\nc\r\n"),
        ("a\n\nb", "a\nb"),
        ("重复\n原值\n重复\n", "重复\n新值\n重复\n新增\n"),
    ],
)
def test_revision_preserves_original_line_endings(before: str, after: str) -> None:
    fields, _ = present_field_changes(_item([_change(before, after)]))
    assert _version(fields[0], old=True) == before
    assert _version(fields[0], old=False) == after


def test_preview_has_no_detail_text_or_revision_payload() -> None:
    prepared = NewContentPreparedItem(
        _item([_change("旧效果", "新效果")]),
        NewContentItemDetails(
            metadata="ID",
            description="简介",
            side_title="技能",
            side_description="长技能",
            stats=(("体力", "50"),),
        ),
        None,
    )
    row = _content_row("a1", prepared, preview=True)
    assert row.preview and row.change_label == "修改"
    assert row.name == prepared.item.name
    assert not any(
        (
            row.description,
            row.metadata,
            row.side_description,
            row.side_title,
            row.stats,
            row.skill,
            row.diff_fields,
            row.diff_notice,
        )
    )
    assert _content_row("1", prepared).diff_fields
